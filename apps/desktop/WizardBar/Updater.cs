using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
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
    /// version) and run silently for this Windows account. It never downgrades. The release carries no credentials.</summary>
    internal static class Updater
    {
        public const string ReleaseRoot = "https://github.com/datap0nd/wizard/releases/download/desktop-continuous/";
        private const long MaxBytes = 400L * 1024 * 1024;

        private static HttpClient Client()
        {
            ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
            var proxy = WebRequest.GetSystemWebProxy();
            proxy.Credentials = CredentialCache.DefaultCredentials;
            var handler = new HttpClientHandler { Proxy = proxy, UseProxy = true, UseDefaultCredentials = true, AllowAutoRedirect = true };
            var client = new HttpClient(handler) { Timeout = TimeSpan.FromMinutes(10) };
            client.DefaultRequestHeaders.UserAgent.ParseAdd("WizardBar/" + Paths.Version);
            return client;
        }

        /// <summary>The newer release, or null when this one is current.</summary>
        public static async Task<Release> Newer(CancellationToken cancel)
        {
            using (var http = Client())
            {
                var text = await http.GetStringAsync(ReleaseRoot + "wizard-desktop.json");
                cancel.ThrowIfCancellationRequested();
                var values = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(text.TrimStart('﻿'));
                var release = new Release
                {
                    Version = values.TryGetValue("version", out var v) ? v as string : null,
                    Commit = values.TryGetValue("commit", out var c) ? c as string : null,
                    Sha256 = values.TryGetValue("installer_sha256", out var h) ? h as string : null,
                    Size = values.TryGetValue("size", out var s) ? Convert.ToInt64(s) : 0,
                };
                if (!System.Version.TryParse(release.Version ?? "", out var available) || !Regex.IsMatch(release.Sha256 ?? "", "^[a-f0-9]{64}$")
                    || !Regex.IsMatch(release.Commit ?? "", "^[a-f0-9]{40}$") || release.Size <= 0 || release.Size > MaxBytes)
                    throw new InvalidDataException("The release manifest is incomplete; try again in a few minutes.");
                return available > System.Version.Parse(Paths.Version) ? release : null;
            }
        }

        /// <summary>Download and verify the installer; returns its path.</summary>
        public static async Task<string> Download(Release release, CancellationToken cancel)
        {
            var folder = Path.Combine(Path.GetTempPath(), "WizardUpdate");
            Directory.CreateDirectory(folder);
            var target = Path.Combine(folder, "WizardSetup-" + release.Version + ".exe");
            using (var http = Client())
            using (var response = await http.GetAsync(ReleaseRoot + "WizardSetup.exe", HttpCompletionOption.ResponseHeadersRead, cancel))
            {
                response.EnsureSuccessStatusCode();
                using (var source = await response.Content.ReadAsStreamAsync())
                using (var output = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None, 81920, true))
                {
                    var buffer = new byte[81920];
                    long total = 0;
                    int read;
                    while ((read = await source.ReadAsync(buffer, 0, buffer.Length, cancel)) > 0)
                    {
                        total += read;
                        if (total > MaxBytes) throw new InvalidDataException("The download is larger than expected.");
                        await output.WriteAsync(buffer, 0, read, cancel);
                    }
                }
            }
            var info = new FileInfo(target);
            if (info.Length != release.Size) throw new InvalidDataException("The installer download is incomplete.");
            using (var file = File.OpenRead(target))
            {
                if (file.ReadByte() != 'M' || file.ReadByte() != 'Z') throw new InvalidDataException("The download is not a Windows installer.");
                file.Position = 0;
                using (var sha = SHA256.Create())
                {
                    var hash = BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
                    if (hash != release.Sha256) throw new InvalidDataException("The installer's checksum does not match the release; nothing was installed.");
                }
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
