using System;
using System.Drawing;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

namespace WizardBar
{
    /// <summary>Wires the button, the panel, the tray icon, the hotkey, the local service and updates together.</summary>
    internal sealed class WizardContext : ApplicationContext
    {
        private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private readonly Paths paths;
        private readonly BarSettings settings;
        private readonly Backend backend;
        private readonly TopButton button;
        private readonly PanelForm panel;
        private readonly NotifyIcon tray;
        private readonly Hotkey hotkey;
        private readonly ContextMenuStrip menu = new ContextMenuStrip();
        private readonly ToolStripMenuItem showButton = new ToolStripMenuItem("Show the button at the top of the screen");
        private readonly ToolStripMenuItem startWithWindows = new ToolStripMenuItem("Start Wizard when I sign in");
        private readonly ToolStripMenuItem update = new ToolStripMenuItem("Check for updates…");
        private readonly System.Windows.Forms.Timer updateTimer = new System.Windows.Forms.Timer { Interval = 6 * 60 * 60 * 1000 };
        private readonly SynchronizationContext ui;
        private Release pendingUpdate;
        private bool busy, answered, quitting, balloonForUpdate;

        public WizardContext(Paths paths)
        {
            this.paths = paths;
            ui = SynchronizationContext.Current ?? new WindowsFormsSynchronizationContext();
            settings = BarSettings.Load(paths);
            backend = new Backend(paths);
            BuildMenu();
            button = new TopButton(settings) { RightClickMenu = menu };
            panel = new PanelForm(paths, settings);
            tray = new NotifyIcon { Icon = Icons.Tray(), Text = "Wizard", ContextMenuStrip = menu, Visible = true };
            hotkey = new Hotkey();
            button.Clicked += Toggle;
            hotkey.Pressed += Toggle;
            tray.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left) Toggle(); };
            tray.BalloonTipClicked += (s, e) => { if (balloonForUpdate) InstallUpdate(); else ShowPanel(); };
            panel.BusyChanged += value => { busy = value; Refresh(); };
            panel.Finished += Finished;
            panel.UpdateRequested += async () => await UpdateNow();
            panel.VisibleChanged += (s, e) => { if (panel.Visible) { answered = false; Refresh(); } };
            panel.RetryRequested += () => backend.Restart();
            backend.StateChanged += () => ui.Post(_ => OnServiceState(), null);
            SystemEvents.SessionEnding += (s, e) => backend.Stop();
            updateTimer.Tick += async (s, e) => await CheckForUpdate(false);

            _ = panel.Handle;  // create the WebView2 early, so the first click opens a loaded panel
            button.Show();
            button.ApplyVisibility();
            backend.Start();
            updateTimer.Start();
            _ = DelayedUpdateCheck();
            Log.Write("WizardBar " + Paths.Version + " (" + Paths.Commit + ") started; install " + paths.Install + ", home " + paths.Home);
        }

        private void BuildMenu()
        {
            var ask = new ToolStripMenuItem("Ask Wizard", null, (s, e) => ShowPanel()) { ShortcutKeyDisplayString = "Ctrl+Alt+W", Font = new Font(menu.Font, FontStyle.Bold) };
            showButton.Checked = settings.ShowButton;
            showButton.Click += (s, e) =>
            {
                settings.ShowButton = !settings.ShowButton;
                showButton.Checked = settings.ShowButton;
                settings.Save();
                button.ApplyVisibility();
            };
            startWithWindows.Checked = StartsWithWindows();
            startWithWindows.Click += (s, e) => { SetStartWithWindows(!StartsWithWindows()); startWithWindows.Checked = StartsWithWindows(); };
            update.Click += async (s, e) => { if (pendingUpdate != null) InstallUpdate(); else await CheckForUpdate(true); };
            menu.Items.AddRange(new ToolStripItem[]
            {
                ask,
                new ToolStripMenuItem("Open Wizard in the browser", null, (s, e) => OpenInBrowser()),
                new ToolStripSeparator(),
                new ToolStripMenuItem("Sync the knowledge base now", null, async (s, e) => await SyncNow()),
                showButton,
                startWithWindows,
                new ToolStripSeparator(),
                new ToolStripMenuItem("Settings…", null, (s, e) => { ShowPanel(); panel.OpenSettings(); }),
                new ToolStripMenuItem("Import a settings file…", null, (s, e) => ImportProvision()),
                update,
                new ToolStripMenuItem("Open the log folder", null, (s, e) => PanelForm.OpenFolder(paths.Logs)),
                new ToolStripMenuItem("Restart Wizard", null, (s, e) => backend.Restart()),
                new ToolStripSeparator(),
                new ToolStripMenuItem("About Wizard", null, async (s, e) => await About()),
                new ToolStripMenuItem("Quit Wizard", null, (s, e) => Quit()),
            });
        }

        /// <summary>Called on a thread-pool thread when Wizard is started again while it runs.</summary>
        public void OpenFromAnotherLaunch() => ui.Post(_ => ShowPanel(), null);

        private void Toggle()
        {
            if (panel.IsInFront) panel.HidePanel(); else ShowPanel();
        }

        private void ShowPanel()
        {
            panel.ShowUnder(button.Bounds, button.Visible);
            answered = false;
            Refresh();
        }

        private void Finished(string question, bool ok)
        {
            if (panel.IsInFront) return;
            answered = true;
            Refresh();
            var text = question.Length > 120 ? question.Substring(0, 117) + "…" : question;
            balloonForUpdate = false;
            tray.ShowBalloonTip(8000, ok ? "Wizard answered" : "Wizard could not answer", text.Length > 0 ? text : "Open Wizard to read it.",
                ok ? ToolTipIcon.Info : ToolTipIcon.Warning);
        }

        private void OnServiceState()
        {
            switch (backend.State)
            {
                case ServiceState.Ready:
                    panel.ServiceReady(backend.BaseUrl);
                    break;
                case ServiceState.Failed:
                    panel.ServiceProblem(backend.Problem ?? "Wizard stopped.", true);
                    break;
                case ServiceState.Starting:
                    panel.ServiceProblem("Starting Wizard…", false);
                    break;
            }
            Refresh();
        }

        private void Refresh()
        {
            var look = backend.State == ServiceState.Failed ? ButtonLook.Failed
                : backend.State != ServiceState.Ready ? ButtonLook.Starting
                : busy ? ButtonLook.Working
                : answered ? ButtonLook.Answered
                : ButtonLook.Ready;
            button.Look = look;
            tray.Text = look switch
            {
                ButtonLook.Failed => "Wizard stopped: open the menu for the log",
                ButtonLook.Starting => "Wizard is starting",
                ButtonLook.Working => "Wizard is working on your question",
                ButtonLook.Answered => "Wizard answered your question",
                _ => "Wizard (Ctrl+Alt+W)",
            };
        }

        private void OpenInBrowser()
        {
            try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(backend.BaseUrl + "/") { UseShellExecute = true }); }
            catch (Exception error) { Log.Error("open browser", error); }
        }

        private async Task SyncNow()
        {
            if (backend.State != ServiceState.Ready) { Balloon("Wizard is not running yet", "Try again when the button says Ask Wizard."); return; }
            try
            {
                var result = await backend.Control("sync", HttpMethod.Post);
                var message = Backend.Text(result, "message") ?? Backend.Text(result, "error") ?? "Done.";
                var restarting = Backend.Text(result, "restarting") == "True";
                Balloon("Knowledge base", message + (restarting ? " Wizard restarts to load it." : ""));
            }
            catch (Exception error)
            {
                Log.Error("sync", error);
                Balloon("Knowledge base", "The sync did not finish: " + error.Message);
            }
        }

        private void ImportProvision()
        {
            using (var dialog = new OpenFileDialog { Title = "Import Wizard settings", Filter = "Wizard settings (*.provision)|*.provision|All files (*.*)|*.*" })
            {
                if (dialog.ShowDialog() != DialogResult.OK) return;
                try
                {
                    File.Copy(dialog.FileName, paths.Provision, true);
                    Log.Write("settings file offered for import: " + dialog.FileName);
                    backend.Restart();
                    Balloon("Wizard settings", "Wizard restarts and imports the settings. If it stops, the log folder says why.");
                }
                catch (Exception error)
                {
                    Log.Error("import", error);
                    MessageBox.Show("The settings file could not be copied: " + error.Message, "Wizard", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
            }
        }

        private async Task About()
        {
            var lines = "Wizard " + Paths.Version + " (" + (Paths.Commit.Length > 12 ? Paths.Commit.Substring(0, 12) : Paths.Commit) + ")\r\n"
                        + "Home: " + paths.Home + "\r\n";
            if (backend.State == ServiceState.Ready)
            {
                try
                {
                    var status = await backend.Control("status", HttpMethod.Get);
                    var commit = Backend.Text(status, "knowledge_base", "commit");
                    var repo = Backend.Text(status, "knowledge_base", "repo");
                    lines += repo != null
                        ? "Knowledge base: " + repo + " at " + (commit != null && commit.Length >= 12 ? commit.Substring(0, 12) : "not synced yet")
                          + " (checked " + (Backend.Text(status, "knowledge_base", "checked_at") ?? "never") + ")\r\n"
                        : "Knowledge base: not configured (import the settings file from your administrator)\r\n";
                    var error = Backend.Text(status, "knowledge_base", "last_error");
                    if (!string.IsNullOrEmpty(error)) lines += "Last sync problem: " + error + "\r\n";
                    lines += "Company data (PostgreSQL): " + (Backend.Text(status, "postgres") == "True" ? "configured" : "not configured") + "\r\n";
                }
                catch (Exception error) { lines += "Status unavailable: " + error.Message + "\r\n"; }
            }
            else lines += "Service: " + backend.State + (backend.Problem != null ? " - " + backend.Problem : "") + "\r\n";
            MessageBox.Show(lines, "About Wizard", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }

        private async Task DelayedUpdateCheck()
        {
            await Task.Delay(TimeSpan.FromMinutes(2));
            await CheckForUpdate(false);
        }

        /// <summary>The page's Update button: check now and, when a newer release exists, install it (after asking).</summary>
        private async Task UpdateNow()
        {
            if (pendingUpdate == null) await CheckForUpdate(true, announce: false);
            if (pendingUpdate != null) InstallUpdate();
        }

        private async Task CheckForUpdate(bool asked, bool announce = true)
        {
            try
            {
                using (var cancel = new CancellationTokenSource(TimeSpan.FromMinutes(1)))
                    pendingUpdate = await Updater.Newer(cancel.Token);
                settings.LastUpdateCheck = DateTime.UtcNow.ToString("o");
                settings.Save();
                if (pendingUpdate != null)
                {
                    update.Text = "Install update " + pendingUpdate.Version + "…";
                    if (announce) Balloon("Wizard update available", "Version " + pendingUpdate.Version + ". Click here, or choose Install update in the menu.", true);
                }
                else if (asked) MessageBox.Show("Wizard " + Paths.Version + " is up to date.", "Wizard", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            catch (Exception error)
            {
                Log.Error("update check", error);
                if (asked) MessageBox.Show("Wizard could not check for updates: " + error.Message, "Wizard", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }

        private async void InstallUpdate()
        {
            var release = pendingUpdate;
            if (release == null) return;
            var running = busy ? " A question is still running; it will be stopped." : "";
            if (MessageBox.Show("Install Wizard " + release.Version + " now? Wizard closes for a moment and starts again." + running,
                    "Wizard update", MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return;
            try
            {
                Balloon("Wizard update", "Downloading version " + release.Version + "…");
                string installer;
                using (var cancel = new CancellationTokenSource(TimeSpan.FromMinutes(15)))
                    installer = await Updater.Download(release, cancel.Token);
                Log.Write("installing update " + release.Version + " from " + installer);
                await Task.Run(() => backend.Stop());
                Updater.Install(installer, paths);
                Quit(stopService: false);
            }
            catch (Exception error)
            {
                Log.Error("update", error);
                MessageBox.Show("The update was not installed: " + error.Message, "Wizard update", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }

        private void Balloon(string title, string text, bool forUpdate = false)
        {
            balloonForUpdate = forUpdate;
            tray.ShowBalloonTip(6000, title, text, ToolTipIcon.Info);
        }

        private string Command => "\"" + Application.ExecutablePath + "\"";

        private bool StartsWithWindows()
        {
            using (var key = Registry.CurrentUser.OpenSubKey(RunKey)) return key?.GetValue("Wizard") is string value && value.Length > 0;
        }

        private void SetStartWithWindows(bool on)
        {
            using (var key = Registry.CurrentUser.CreateSubKey(RunKey))
            {
                if (on) key.SetValue("Wizard", Command); else key.DeleteValue("Wizard", false);
            }
        }

        public void Quit(bool stopService = true)
        {
            if (quitting) return;
            quitting = true;
            Log.Write("quitting");
            if (stopService) backend.Stop();
            tray.Visible = false;
            panel.PrepareExit();
            ExitThread();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                hotkey.Dispose();
                tray.Dispose();
                updateTimer.Dispose();
                button.Dispose();
                panel.Dispose();
                backend.Dispose();
                menu.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
