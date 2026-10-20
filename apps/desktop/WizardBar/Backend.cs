using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace WizardBar
{
    internal enum ServiceState { Starting, Ready, Failed, Stopped }

    /// <summary>Runs Wizard's local service (portable Python, run.py --desktop) and keeps it running: restarts it at once
    /// when it asks (exit code 75, a new knowledge base), after a crash with a back-off, and when it stops answering.
    /// Talks to it on 127.0.0.1 only; the control endpoints need a token generated for each launch.</summary>
    internal sealed class Backend : IDisposable
    {
        public const int RestartExitCode = 75;
        private readonly Paths paths;
        private readonly HttpClient http = new HttpClient(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(10) };
        private readonly List<DateTime> crashes = new List<DateTime>();
        private readonly object gate = new object();
        private readonly System.Threading.Timer watchdog;
        private Process process;
        private string token;
        private bool stopping;
        private int missedHealth;
        private int generation;

        public ServiceState State { get; private set; } = ServiceState.Stopped;
        public string Problem { get; private set; }
        public int Port { get; private set; }
        public string BaseUrl => "http://127.0.0.1:" + Port;
        /// <summary>Raised on a thread-pool thread; the UI marshals it.</summary>
        public event Action StateChanged;

        public Backend(Paths paths)
        {
            this.paths = paths;
            Port = paths.Port();
            watchdog = new System.Threading.Timer(_ => Watch(), null, Timeout.Infinite, Timeout.Infinite);
        }

        public void Start()
        {
            lock (gate)
            {
                stopping = false;
                if (process != null && !process.HasExited) return;
                Launch();
            }
        }

        private void Launch()
        {
            if (!File.Exists(paths.Python) || !File.Exists(paths.RunPy))
            {
                Fail("Wizard's files are missing (" + paths.Python + "). Reinstall Wizard.");
                return;
            }
            KillLeftover();
            token = NewToken();
            Port = paths.Port();
            var start = new ProcessStartInfo(paths.Python, "-X utf8 \"" + paths.RunPy + "\" --home \"" + paths.Home + "\" --desktop")
            {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                WorkingDirectory = paths.Home, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            start.EnvironmentVariables["WIZARD_CONTROL_TOKEN"] = token;
            start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            start.EnvironmentVariables.Remove("PYTHONHOME");
            start.EnvironmentVariables.Remove("PYTHONPATH");
            var output = Path.Combine(paths.Logs, "service-output.log");
            try
            {
                if (File.Exists(output) && new FileInfo(output).Length > 2_000_000) File.Delete(output);
                var started = new Process { StartInfo = start, EnableRaisingEvents = true };
                started.OutputDataReceived += (s, e) => Append(output, e.Data);
                started.ErrorDataReceived += (s, e) => Append(output, e.Data);
                var mine = Interlocked.Increment(ref generation);
                started.Exited += (s, e) => OnExited(started, mine);
                started.Start();
                started.BeginOutputReadLine();
                started.BeginErrorReadLine();
                process = started;
                File.WriteAllText(Path.Combine(paths.Logs, "service.pid"), started.Id.ToString());
                Log.Write("service started, pid " + started.Id + ", port " + Port);
                SetState(ServiceState.Starting, null);
                _ = WaitUntilReady(started, mine);
            }
            catch (Exception error)
            {
                Log.Error("service start", error);
                Fail("Wizard's service could not start: " + error.Message);
            }
        }

        private static string NewToken()
        {
            var bytes = new byte[32];
            using (var random = RandomNumberGenerator.Create()) random.GetBytes(bytes);
            return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();
        }

        private static void Append(string file, string line)
        {
            if (line == null) return;
            try { File.AppendAllText(file, line + Environment.NewLine, Encoding.UTF8); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }

        /// <summary>A service left running by a bar that crashed holds the port: stop it if it is ours.</summary>
        private void KillLeftover()
        {
            var pidFile = Path.Combine(paths.Logs, "service.pid");
            try
            {
                if (!File.Exists(pidFile) || !int.TryParse(File.ReadAllText(pidFile).Trim(), out var pid)) return;
                using (var old = Process.GetProcessById(pid))
                {
                    var exe = old.MainModule?.FileName ?? "";
                    if (exe.Equals(paths.Python, StringComparison.OrdinalIgnoreCase))
                    {
                        Log.Write("stopping a leftover service, pid " + pid);
                        old.Kill();
                        old.WaitForExit(5000);
                    }
                }
            }
            catch (ArgumentException) { }  // no such process
            catch (Exception error) { Log.Error("leftover service", error); }
        }

        private async Task WaitUntilReady(Process started, int mine)
        {
            var deadline = DateTime.UtcNow.AddSeconds(120);
            while (DateTime.UtcNow < deadline && mine == generation && !started.HasExited)
            {
                if (await Healthy().ConfigureAwait(false))
                {
                    missedHealth = 0;
                    SetState(ServiceState.Ready, null);
                    watchdog.Change(15000, 15000);
                    return;
                }
                await Task.Delay(400).ConfigureAwait(false);
            }
            if (mine == generation && !started.HasExited)
            {
                Log.Write("service did not answer within 2 minutes; restarting it");
                TryKill(started);
            }
        }

        private async Task<bool> Healthy()
        {
            try
            {
                using (var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(5)))
                using (var response = await http.GetAsync(BaseUrl + "/api/v1/health", cancel.Token).ConfigureAwait(false))
                    return response.IsSuccessStatusCode;
            }
            catch (Exception) { return false; }
        }

        private void Watch()
        {
            if (State != ServiceState.Ready || stopping) return;
            if (Healthy().GetAwaiter().GetResult()) { missedHealth = 0; return; }
            if (++missedHealth < 3) return;
            Log.Write("service stopped answering; restarting it");
            missedHealth = 0;
            lock (gate) { if (process != null) TryKill(process); }
        }

        private void OnExited(Process exited, int mine)
        {
            int code;
            try { code = exited.ExitCode; } catch (InvalidOperationException) { code = -1; }
            Log.Write("service exited with code " + code);
            lock (gate)
            {
                if (mine != generation) return;
                watchdog.Change(Timeout.Infinite, Timeout.Infinite);
                process = null;
                if (stopping) { SetState(ServiceState.Stopped, null); return; }
                if (code == RestartExitCode) { Launch(); return; }
                crashes.Add(DateTime.UtcNow);
                crashes.RemoveAll(t => t < DateTime.UtcNow.AddMinutes(-10));
                if (code == 2 || crashes.Count >= 5)
                {
                    Fail(code == 2
                        ? "Wizard's settings have a problem. Open the log folder (logs\\wizard.log or service-output.log) for the reason."
                        : "Wizard's service keeps stopping. Open the log folder for the reason, then use Restart Wizard.");
                    return;
                }
                SetState(ServiceState.Starting, null);
                var wait = TimeSpan.FromSeconds(2 * crashes.Count);
                Task.Delay(wait).ContinueWith(_ => { lock (gate) { if (!stopping && process == null && mine == generation) Launch(); } });
            }
        }

        private void Fail(string problem)
        {
            Log.Write("FAILED: " + problem);
            SetState(ServiceState.Failed, problem);
        }

        private void SetState(ServiceState state, string problem)
        {
            State = state;
            Problem = problem;
            try { StateChanged?.Invoke(); } catch (Exception error) { Log.Error("state change", error); }
        }

        private static void TryKill(Process target)
        {
            try { if (!target.HasExited) target.Kill(); } catch (Exception) { }
        }

        public void Restart()
        {
            lock (gate)
            {
                crashes.Clear();
                stopping = false;
                if (process != null && !process.HasExited)
                {
                    // Exits with code 75 when asked to restart; a kill counts as a crash, so ask first.
                    var current = process;
                    Interlocked.Increment(ref generation);
                    process = null;
                    _ = Control("stop", HttpMethod.Post).ContinueWith(_ =>
                    {
                        if (!current.WaitForExit(8000)) TryKill(current);
                        lock (gate) { if (!stopping) Launch(); }
                    });
                    SetState(ServiceState.Starting, null);
                    return;
                }
                Launch();
            }
        }

        /// <summary>Stop the service (quit, update, sign-out); waits up to eight seconds, then kills it.</summary>
        public void Stop()
        {
            Process current;
            lock (gate)
            {
                stopping = true;
                watchdog.Change(Timeout.Infinite, Timeout.Infinite);
                current = process;
            }
            if (current == null || current.HasExited) return;
            try { Control("stop", HttpMethod.Post).Wait(3000); } catch (Exception) { }
            if (!current.WaitForExit(8000)) TryKill(current);
        }

        public async Task<Dictionary<string, object>> Control(string action, HttpMethod method, object body = null)
        {
            using (var request = new HttpRequestMessage(method, BaseUrl + "/internal/v1/desktop/" + action))
            {
                request.Headers.Add("X-Wizard-Control", token ?? "");
                request.Headers.Add("X-Wizard-Request", "1");
                if (method == HttpMethod.Post)
                    request.Content = new StringContent(body == null ? "{}" : new JavaScriptSerializer().Serialize(body), Encoding.UTF8, "application/json");
                using (var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(method == HttpMethod.Post && action == "sync" ? 300 : 10)))
                using (var response = await http.SendAsync(request, cancel.Token).ConfigureAwait(false))
                {
                    var text = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                    var parsed = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(string.IsNullOrWhiteSpace(text) ? "{}" : text)
                                 ?? new Dictionary<string, object>();
                    if (!response.IsSuccessStatusCode && !parsed.ContainsKey("error")) parsed["error"] = "HTTP " + (int)response.StatusCode;
                    return parsed;
                }
            }
        }

        public static string Text(Dictionary<string, object> values, params string[] path)
        {
            object current = values;
            foreach (var key in path)
            {
                if (current is Dictionary<string, object> map && map.TryGetValue(key, out var next)) current = next;
                else return null;
            }
            return current?.ToString();
        }

        public void Dispose()
        {
            watchdog.Dispose();
            http.Dispose();
        }
    }
}
