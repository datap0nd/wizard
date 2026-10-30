using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
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
    /// Owner, 30 Oct 2026: GitHub downloads were tightened on the work network, so Wizard goes first where Metronome's
    /// setup.ps1 goes: api.github.com for the newest manifest, and a branch zip from codeload.github.com for the installer
    /// (CI mirrors every release to the desktop-download branch). The release's own download host comes second, and the
    /// pair is tried up to 20 times, 5 seconds apart. The reads run in this process, never through PowerShell (owner,
    /// 30 Oct 2026: Microsoft Defender reported the hidden PowerShell downloads as malware, execution/mdp.powershell.m4192).</summary>
    internal static class Updater
    {
        public const string ReleaseRoot = "https://github.com/datap0nd/wizard/releases/download/desktop-continuous/";
        private const string Manifest = "wizard-desktop.json";
        private const string MirrorManifest = "https://api.github.com/repos/datap0nd/wizard/contents/wizard-desktop.json?ref=desktop-download";
        private const string MirrorZip = "https://github.com/datap0nd/wizard/archive/refs/heads/desktop-download.zip";
        public const int Attempts = 20;
        private static readonly TimeSpan Pause = TimeSpan.FromSeconds(5);
        private const long MaxBytes = 400L * 1024 * 1024;

        /// <summary>One address to read into File. `Check` throws for a file that is not what was asked for (cut short, a
        /// proxy's page, another release), which counts as a failed read.</summary>
        private sealed class Route
        {
            public string Url;
            public string File;
            public string Accept;
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
                        await Read(route, cancel);
                        route.Check(route.File);
                        if (attempt > 1 || route != routes[0]) Log.Write("read " + route.Url + " on attempt " + attempt + " of " + Attempts);
                        return;
                    }
                    catch (Exception error) when (!(error is OperationCanceledException) && !cancel.IsCancellationRequested)
                    {
                        // HttpClient's own message ("An error occurred while sending the request.") hides the cause.
                        var reason = error.GetBaseException().Message;
                        errors.Add(new Uri(route.Url).Host + ": " + reason);
                        Log.Write("attempt " + attempt + " of " + Attempts + " failed (" + route.Url + "): " + reason);
                    }
                }
                last = string.Join("; ", errors);
                failed?.Invoke(attempt, last);
                if (attempt < Attempts) await Task.Delay(Pause, cancel);
            }
            throw new IOException("Wizard tried " + Attempts + " times. " + last);
        }

        /// <summary>One read into route.File, in this process, with the network settings Windows PowerShell's
        /// Invoke-WebRequest uses (the same .NET Framework stack): Windows' proxy settings, a PAC script included, and the
        /// person's proxy sign-in, over TLS 1.2. Each redirect hop gets its own proxy. A read that outlasts route.Limit is
        /// stopped.</summary>
        private static async Task Read(Route route, CancellationToken cancel)
        {
            ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
            var proxy = WebRequest.DefaultWebProxy;
            if (proxy != null) proxy.Credentials = CredentialCache.DefaultNetworkCredentials;
            var handler = new HttpClientHandler { Proxy = proxy, UseProxy = proxy != null, AllowAutoRedirect = true };
            using (var limit = CancellationTokenSource.CreateLinkedTokenSource(cancel))
            using (var http = new HttpClient(handler) { Timeout = System.Threading.Timeout.InfiniteTimeSpan })
            using (var request = new HttpRequestMessage(HttpMethod.Get, route.Url))
            {
                request.Headers.UserAgent.ParseAdd("WizardBar/" + Paths.Version);
                if (!string.IsNullOrEmpty(route.Accept)) request.Headers.TryAddWithoutValidation("Accept", route.Accept);
                limit.CancelAfter(route.Limit);
                try
                {
                    using (var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, limit.Token))
                    using (limit.Token.Register(response.Dispose))
                    {
                        if (!response.IsSuccessStatusCode)
                            throw new IOException("The remote server returned an error: (" + (int)response.StatusCode + ") " + response.ReasonPhrase + ".");
                        using (var source = await response.Content.ReadAsStreamAsync())
                        using (var output = new FileStream(route.File, FileMode.Create, FileAccess.Write, FileShare.None, 81920, true))
                        {
                            var buffer = new byte[81920];
                            long total = 0;
                            int read;
                            while ((read = await source.ReadAsync(buffer, 0, buffer.Length, limit.Token)) > 0)
                            {
                                total += read;
                                if (total > MaxBytes) throw new InvalidDataException("The download is larger than expected.");
                                await output.WriteAsync(buffer, 0, read, limit.Token);
                            }
                        }
                    }
                }
                catch (Exception) when (limit.IsCancellationRequested && !cancel.IsCancellationRequested)
                {
                    // The stream of a stalled read is closed when the limit passes; whatever that throws is a time-out.
                    throw new TimeoutException("No answer within " + (route.Limit.TotalMinutes >= 1
                        ? (int)route.Limit.TotalMinutes + " minute(s)." : (int)route.Limit.TotalSeconds + " seconds."));
                }
            }
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
                new Route { Url = MirrorManifest, File = file, Accept = "application/vnd.github.raw+json",
                            Limit = TimeSpan.FromSeconds(30), Check = read },
                // The release's own manifest, at a fresh address so no proxy on the way answers with an old one.
                new Route { Url = ReleaseRoot + Manifest + "?nocache=" + DateTimeOffset.UtcNow.ToUnixTimeSeconds(), File = file,
                            Limit = TimeSpan.FromSeconds(30), Check = read },
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
                    new Route { Url = MirrorZip + "?nocache=" + DateTimeOffset.UtcNow.ToUnixTimeSeconds(), File = zip,
                                Limit = TimeSpan.FromMinutes(10), Check = path => { Unpack(path, target); Verify(target, release); } },
                    new Route { Url = ReleaseRoot + "WizardSetup.exe", File = target, Limit = TimeSpan.FromMinutes(10),
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
