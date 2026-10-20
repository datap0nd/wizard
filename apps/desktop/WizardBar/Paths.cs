using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Web.Script.Serialization;

namespace WizardBar
{
    /// <summary>Where things are. The install folder (replaced by every update) holds bar\, app\ and runtime\python\; the
    /// home folder (%LOCALAPPDATA%\Wizard, kept) holds .env, data\, logs\ and the WebView2 profile.</summary>
    internal sealed class Paths
    {
        public string Install { get; }
        public string Home { get; }
        public string Python => Path.Combine(Install, "runtime", "python", "python.exe");
        public string RunPy => Path.Combine(Install, "app", "run.py");
        public string Logs => Path.Combine(Home, "logs");
        public string WebView => Path.Combine(Home, "WebView2");
        public string EnvFile => Path.Combine(Home, ".env");
        public string Provision => Path.Combine(Home, "wizard.provision");
        public string Settings => Path.Combine(Home, "bar.json");
        /// <summary>Outlook attachments and messages dropped on the button, saved so Wizard can read them (kept a day).</summary>
        public string Dropped => Path.Combine(Home, "dropped");

        public Paths(string install, string home)
        {
            Install = Path.GetFullPath(install);
            Home = Path.GetFullPath(home);
            Directory.CreateDirectory(Home);
            Directory.CreateDirectory(Logs);
        }

        public static Paths FromArguments(string[] args)
        {
            string install = null, home = null;
            for (var i = 0; i + 1 < args.Length; i++)
            {
                if (args[i] == "--install") install = args[i + 1];
                if (args[i] == "--home") home = args[i + 1];
            }
            var exeFolder = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? ".";
            install ??= Path.GetFullPath(Path.Combine(exeFolder, ".."));
            home ??= Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Wizard");
            return new Paths(install, home);
        }

        public static string Version
        {
            get
            {
                var location = Assembly.GetExecutingAssembly().Location;
                var info = FileVersionInfo.GetVersionInfo(location);
                return info.FileMajorPart + "." + info.FileMinorPart + "." + info.FileBuildPart + "." + info.FilePrivatePart;
            }
        }

        public static string Commit => Assembly.GetExecutingAssembly()
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "dev";

        /// <summary>WIZARD_PORT from the home .env (run.py --desktop writes 8771 on first start).</summary>
        public int Port()
        {
            try
            {
                foreach (var raw in File.ReadAllLines(EnvFile))
                {
                    var line = raw.Trim();
                    if (!line.StartsWith("WIZARD_PORT", StringComparison.Ordinal)) continue;
                    var parts = line.Split(new[] { '=' }, 2);
                    if (parts.Length == 2 && parts[0].Trim() == "WIZARD_PORT" && int.TryParse(parts[1].Trim().Trim('"', '\''), out var port)
                        && port > 0 && port < 65536) return port;
                }
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            return 8771;
        }
    }

    internal static class Log
    {
        private static readonly object Gate = new object();
        private static string file;

        public static void Init(Paths paths) => file = Path.Combine(paths.Logs, "bar.log");

        public static void Write(string message)
        {
            if (file == null) return;
            lock (Gate)
            {
                try
                {
                    var info = new FileInfo(file);
                    if (info.Exists && info.Length > 2_000_000) File.Copy(file, file + ".1", true);
                    if (info.Exists && info.Length > 2_000_000) File.Delete(file);
                    File.AppendAllText(file, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + message + Environment.NewLine, Encoding.UTF8);
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }

        public static void Error(string where, Exception error) => Write("ERROR " + where + ": " + error);
    }

    /// <summary>The bar's own preferences (button position, panel size), in home\bar.json.</summary>
    internal sealed class BarSettings
    {
        public bool ShowButton { get; set; } = true;
        public double ButtonX { get; set; } = 0.5;
        public int PanelWidth { get; set; }
        public int PanelHeight { get; set; }
        public string LastUpdateCheck { get; set; }

        private string path;

        public static BarSettings Load(Paths paths)
        {
            BarSettings settings = null;
            try
            {
                if (File.Exists(paths.Settings))
                    settings = new JavaScriptSerializer().Deserialize<BarSettings>(File.ReadAllText(paths.Settings));
            }
            catch (Exception error) { Log.Error("settings", error); }
            settings ??= new BarSettings();
            settings.path = paths.Settings;
            if (double.IsNaN(settings.ButtonX) || settings.ButtonX < 0 || settings.ButtonX > 1) settings.ButtonX = 0.5;
            return settings;
        }

        public void Save()
        {
            try
            {
                var values = new Dictionary<string, object>
                {
                    ["ShowButton"] = ShowButton, ["ButtonX"] = ButtonX, ["PanelWidth"] = PanelWidth,
                    ["PanelHeight"] = PanelHeight, ["LastUpdateCheck"] = LastUpdateCheck,
                };
                File.WriteAllText(path, new JavaScriptSerializer().Serialize(values), Encoding.UTF8);
            }
            catch (Exception error) { Log.Error("settings", error); }
        }
    }
}
