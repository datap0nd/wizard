using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace WizardBar
{
    internal sealed class Release
    {
        public string Version;
        public string Commit;
        public string Sha256;
        public long Size;
    }

    /// <summary>Updates from the desktop-continuous release CI publishes on every push to main: a manifest names the
    /// version and the installer's SHA-256, the installer is downloaded, checked (size, Windows executable, hash,
    /// version) and run silently for this Windows account. It never downgrades. The release carries no credentials.
    ///
    /// Owner, 30 Oct 2026: GitHub downloads were tightened on the work network, so Wizard updates the way Metronome's
    /// setup.ps1 does. Every read is Windows PowerShell's Invoke-WebRequest -UseBasicParsing over TLS 1.2 (Windows' proxy
    /// settings and the person's proxy sign-in), tried up to 20 times, 5 seconds apart, and it goes first where setup.ps1
    /// goes: api.github.com for the newest manifest, and a branch zip from codeload.github.com for the installer (CI
    /// mirrors every release to the desktop-download branch). The release's own download host comes second.</summary>
    internal static class Updater
    {
        public const string ReleaseRoot = "https://github.com/datap0nd/wizard/releases/download/desktop-continuous/";
        private const string Manifest = "wizard-desktop.json";
        private const string MirrorManifest = "https://api.github.com/repos/datap0nd/wizard/contents/wizard-desktop.json?ref=desktop-download";
        private const string MirrorZip = "https://github.com/datap0nd/wizard/archive/refs/heads/desktop-download.zip";
        public const int Attempts = 20;
        private static readonly TimeSpan Pause = TimeSpan.FromSeconds(5);
        private const long MaxBytes = 400L * 1024 * 1024;

        /// <summary>One read. The address, the file, the Accept header and the time limit reach PowerShell as environment
        /// variables, never as script text. Setting TLS 1.2 and the proxy sign-in may be refused under a locked-down
        /// PowerShell; the read then goes ahead with Windows' defaults. The error goes to standard output, readable in any
        /// language mode.</summary>
        private const string Script =
            "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'\n" +
            "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}\n" +
            "try { [Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials } catch {}\n" +
            "$headers = @{}\n" +
            "if ($env:WIZARD_DOWNLOAD_ACCEPT) { $headers['Accept'] = $env:WIZARD_DOWNLOAD_ACCEPT }\n" +
            "try {\n" +
            "    Invoke-WebRequest -Uri $env:WIZARD_DOWNLOAD_URL -OutFile $env:WIZARD_DOWNLOAD_FILE -UseBasicParsing " +
            "-UserAgent $env:WIZARD_DOWNLOAD_AGENT -Headers $headers -TimeoutSec ([int]$env:WIZARD_DOWNLOAD_TIMEOUT)\n" +
            "} catch { Write-Output $_.Exception.Message; exit 1 }\n";

        /// <summary>One address to read into File. `Check` throws for a file that is not what was asked for (cut short, a
        /// proxy's page, another release), which counts as a failed read.</summary>
        private sealed class Route
        {
            public string Url;
            public string File;
            public string Accept;
            public int TimeoutSeconds;
            public TimeSpan Limit;
            public Action<string> Check;
        }

        /// <summary>Up to Attempts attempts, Pause apart; each tries the routes in order until one gives a file that passes
        /// its check. `failed` hears of each failed attempt.</summary>
        private static async Task Fetch(Route[] routes, CancellationToken cancel, Action<int, string> failed)
        {
            string last = null;
            for (var attempt = 1; attempt <= Attempts; attempt++)
            {
                var errors = new List<string>();
                foreach (var route in routes)
                {
                    try
                    {
                        if (File.Exists(route.File)) File.Delete(route.File);
                        await PowerShell(route, cancel);
                        if (!File.Exists(route.File)) throw new IOException("PowerShell saved nothing.");
                        route.Check(route.File);
                        if (attempt > 1 || route != routes[0]) Log.Write("read " + route.Url + " on attempt " + attempt + " of " + Attempts);
                        return;
                    }
                    catch (Exception error) when (!(error is OperationCanceledException) && !cancel.IsCancellationRequested)
                    {
                        errors.Add(new Uri(route.Url).Host + ": " + error.Message);
                        Log.Write("attempt " + attempt + " of " + Attempts + " failed (" + route.Url + "): " + error.Message);
                    }
                }
                last = string.Join("; ", errors);
                failed?.Invoke(attempt, last);
                if (attempt < Attempts) await Task.Delay(Pause, cancel);
            }
            throw new IOException("Wizard tried " + Attempts + " times. " + last);
        }

        private static Task PowerShell(Route route, CancellationToken cancel)
        {
            return Task.Run(() =>
            {
                var exe = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
                var encoded = Convert.ToBase64String(System.Text.Encoding.Unicode.GetBytes(Script));
                var start = new ProcessStartInfo(exe, "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + encoded)
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };
                start.EnvironmentVariables["WIZARD_DOWNLOAD_URL"] = route.Url;
                start.EnvironmentVariables["WIZARD_DOWNLOAD_FILE"] = route.File;
                start.EnvironmentVariables["WIZARD_DOWNLOAD_ACCEPT"] = route.Accept ?? "";
                start.EnvironmentVariables["WIZARD_DOWNLOAD_AGENT"] = "WizardBar/" + Paths.Version;
                start.EnvironmentVariables["WIZARD_DOWNLOAD_TIMEOUT"] = route.TimeoutSeconds.ToString();
                using (var process = Process.Start(start))
                {
                    var output = process.StandardOutput.ReadToEndAsync();
                    var errors = process.StandardError.ReadToEndAsync();
                    bool done;
                    using (cancel.Register(() => Stop(process)))
                        done = process.WaitForExit((int)route.Limit.TotalMilliseconds);
                    if (!done)
                    {
                        Stop(process);
                        throw new TimeoutException("No answer within " + (int)route.Limit.TotalMinutes + " minute(s).");
                    }
                    cancel.ThrowIfCancellationRequested();
                    process.WaitForExit();
                    if (process.ExitCode != 0)
                        throw new IOException(FirstLine(output.Result) ?? FirstLine(errors.Result) ?? "PowerShell exited with " + process.ExitCode + ".");
                }
            });
        }

        private static void Stop(Process process)
        {
            try { if (!process.HasExited) process.Kill(); }
            catch (Exception error) { Log.Write("could not stop the download: " + error.Message); }
        }

        /// <summary>The first line that says something; PowerShell's own progress records (CLIXML) are not a message.</summary>
        private static string FirstLine(string text)
        {
            foreach (var line in (text ?? "").Split('\n'))
            {
                var trimmed = line.Trim();
                if (trimmed.Length > 0 && !trimmed.StartsWith("#< CLIXML") && !trimmed.StartsWith("<Objs")) return trimmed;
            }
            return null;
        }

        private static string Folder()
        {
            var folder = Path.Combine(Path.GetTempPath(), "WizardUpdate");
            Directory.CreateDirectory(folder);
            return folder;
        }

        private static Release Parse(string text)
        {
            Dictionary<string, object> values;
            try { values = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(text.TrimStart('﻿')); }
            catch (ArgumentException) { throw new InvalidDataException("The answer is not a release manifest."); }
            catch (InvalidOperationException) { throw new InvalidDataException("The answer is not a release manifest."); }
            var release = new Release
            {
                Version = values != null && values.TryGetValue("version", out var v) ? v as string : null,
                Commit = values != null && values.TryGetValue("commit", out var c) ? c as string : null,
                Sha256 = values != null && values.TryGetValue("installer_sha256", out var h) ? h as string : null,
                Size = values != null && values.TryGetValue("size", out var s) && s != null ? Convert.ToInt64(s) : 0,
            };
            if (!System.Version.TryParse(release.Version ?? "", out _) || !Regex.IsMatch(release.Sha256 ?? "", "^[a-f0-9]{64}$")
                || !Regex.IsMatch(release.Commit ?? "", "^[a-f0-9]{40}$") || release.Size <= 0 || release.Size > MaxBytes)
                throw new InvalidDataException("The release manifest is incomplete; try again in a few minutes.");
            return release;
        }

        /// <summary>The newer release, or null when this one is current. `failed` hears of each failed attempt.</summary>
        public static async Task<Release> Newer(CancellationToken cancel, Action<int, string> failed = null)
        {
            var file = Path.Combine(Folder(), Manifest);
            Release release = null;
            Action<string> read = path => release = Parse(File.ReadAllText(path));
            await Fetch(new[]
            {
                // The mirror branch's manifest from api.github.com, as setup.ps1 asks it for its branch's newest commit.
                new Route { Url = MirrorManifest, File = file, Accept = "application/vnd.github.raw+json", TimeoutSeconds = 30,
                            Limit = TimeSpan.FromMinutes(1), Check = read },
                // The release's own manifest, at a fresh address so no proxy on the way answers with an old one.
                new Route { Url = ReleaseRoot + Manifest + "?nocache=" + DateTimeOffset.UtcNow.ToUnixTimeSeconds(), File = file,
                            TimeoutSeconds = 30, Limit = TimeSpan.FromMinutes(1), Check = read },
            }, cancel, failed);
            File.Delete(file);
            return System.Version.Parse(release.Version) > System.Version.Parse(Paths.Version) ? release : null;
        }

        /// <summary>The installer is the release's: its size, a Windows executable and its SHA-256.</summary>
        private static void Verify(string path, Release release)
        {
            if (new FileInfo(path).Length != release.Size) throw new InvalidDataException("The installer download is incomplete, or from another release.");
            using (var file = File.OpenRead(path))
            {
                if (file.ReadByte() != 'M' || file.ReadByte() != 'Z') throw new InvalidDataException("The download is not a Windows installer.");
                file.Position = 0;
                using (var sha = SHA256.Create())
                {
                    var hash = BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
                    if (hash != release.Sha256) throw new InvalidDataException("The installer's checksum does not match the release; nothing was installed.");
                }
            }
        }

        /// <summary>WizardSetup.exe out of the mirror branch's zip (its one folder, wizard-desktop-download/).</summary>
        private static void Unpack(string zip, string target)
        {
            using (var archive = new ZipArchive(File.OpenRead(zip), ZipArchiveMode.Read))
            {
                var entry = archive.Entries.FirstOrDefault(e => e.FullName.EndsWith("/WizardSetup.exe", StringComparison.Ordinal));
                if (entry == null) throw new InvalidDataException("The mirror's zip holds no WizardSetup.exe.");
                if (entry.Length > MaxBytes) throw new InvalidDataException("The download is larger than expected.");
                using (var source = entry.Open())
                using (var output = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None))
                    source.CopyTo(output);
            }
        }

        /// <summary>Download and verify the installer; returns its path. A download that is cut short is tried again.</summary>
        public static async Task<string> Download(Release release, CancellationToken cancel, Action<int, string> failed = null)
        {
            var folder = Folder();
            var target = Path.Combine(folder, "WizardSetup-" + release.Version + ".exe");
            var zip = Path.Combine(folder, "desktop-download.zip");
            try
            {
                await Fetch(new[]
                {
                    // The mirror branch as a zip from codeload.github.com: how setup.ps1 downloads Metronome.
                    new Route { Url = MirrorZip + "?nocache=" + DateTimeOffset.UtcNow.ToUnixTimeSeconds(), File = zip, TimeoutSeconds = 0,
                                Limit = TimeSpan.FromMinutes(10), Check = path => { Unpack(path, target); Verify(target, release); } },
                    new Route { Url = ReleaseRoot + "WizardSetup.exe", File = target, TimeoutSeconds = 0, Limit = TimeSpan.FromMinutes(10),
                                Check = path => Verify(path, release) },
                }, cancel, failed);
            }
            finally
            {
                if (File.Exists(zip)) File.Delete(zip);
            }
            var version = FileVersionInfo.GetVersionInfo(target);
            var stamped = version.FileMajorPart + "." + version.FileMinorPart + "." + version.FileBuildPart + "." + version.FilePrivatePart;
            if (stamped != release.Version) throw new InvalidDataException("The installer's version does not match the release.");
            return target;
        }

        /// <summary>Run the installer silently for this account. Setup closes WizardBar and starts the new one.</summary>
        public static void Install(string installer, Paths paths)
        {
            var log = Path.Combine(paths.Logs, "update-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".log");
            Process.Start(new ProcessStartInfo(installer, "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG=\"" + log + "\"")
            {
                UseShellExecute = false,
            });
        }
    }
}
