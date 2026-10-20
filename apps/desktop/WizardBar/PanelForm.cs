using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace WizardBar
{
    /// <summary>The panel under the button: Wizard's compact view (/quick) in WebView2. It hides instead of closing, so a
    /// question keeps running and the conversation is still there next time. Only Wizard's own local pages load inside;
    /// every other link (Google sign-in, "open in a full window", reports) opens in the default browser.</summary>
    internal sealed class PanelForm : Form
    {
        private static readonly Color Page = Color.FromArgb(244, 243, 239);
        private const int Grip = 5;
        private readonly Paths paths;
        private readonly BarSettings settings;
        private readonly WebView2 web = new WebView2 { Dock = DockStyle.Fill };
        private readonly Panel notice = new Panel { Dock = DockStyle.Fill, BackColor = Page, Padding = new Padding(28) };
        private readonly Label noticeText = new Label { Dock = DockStyle.Top, AutoSize = false, Height = 120, Font = new Font("Segoe UI", 11f), ForeColor = Color.FromArgb(40, 40, 46) };
        private readonly LinkLabel retry = new LinkLabel { Dock = DockStyle.Top, Text = "Restart Wizard", Font = new Font("Segoe UI", 10f), Height = 28, Visible = false };
        private readonly LinkLabel logs = new LinkLabel { Dock = DockStyle.Top, Text = "Open the log folder", Font = new Font("Segoe UI", 10f), Height = 28, Visible = false };
        private string origin;
        private bool webReady, loaded, exiting;

        public event Action<bool> BusyChanged;
        public event Action<string, bool> Finished;
        public event Action RetryRequested;

        public PanelForm(Paths paths, BarSettings settings)
        {
            this.paths = paths;
            this.settings = settings;
            Text = "Wizard";
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = true;
            StartPosition = FormStartPosition.Manual;
            BackColor = Color.White;
            Padding = new Padding(Grip);
            KeyPreview = true;
            MinimumSize = new Size(420, 360);
            Icon = Icons.App();
            notice.Controls.Add(logs);
            notice.Controls.Add(retry);
            notice.Controls.Add(noticeText);
            // The notice covers the page until it loads; WebView2 stays visible underneath so it can initialise early.
            Controls.Add(notice);
            Controls.Add(web);
            retry.LinkClicked += (s, e) => RetryRequested?.Invoke();
            logs.LinkClicked += (s, e) => OpenFolder(paths.Logs);
            ShowNotice("Starting Wizard…", false);
        }

        protected override CreateParams CreateParams
        {
            get
            {
                var p = base.CreateParams;
                p.ClassStyle |= Native.CS_DROPSHADOW;
                return p;
            }
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            Native.RoundCorners(Handle);
            InitializeWeb();
        }

        private async void InitializeWeb()
        {
            try
            {
                var environment = await CoreWebView2Environment.CreateAsync(null, paths.WebView);
                await web.EnsureCoreWebView2Async(environment);
                var core = web.CoreWebView2;
                core.Settings.AreDevToolsEnabled = false;
                core.Settings.IsStatusBarEnabled = false;
                core.Settings.AreBrowserAcceleratorKeysEnabled = false;
                core.Settings.IsBuiltInErrorPageEnabled = false;
                core.Settings.AreDefaultContextMenusEnabled = true;
                core.NavigationStarting += (s, e) =>
                {
                    if (origin != null && e.Uri.StartsWith(origin + "/", StringComparison.OrdinalIgnoreCase)) return;
                    e.Cancel = true;
                    OpenExternal(e.Uri);
                };
                core.NewWindowRequested += (s, e) => { e.Handled = true; OpenExternal(e.Uri); };
                core.NavigationCompleted += (s, e) =>
                {
                    loaded = e.IsSuccess;
                    if (e.IsSuccess) notice.Visible = false;
                };
                core.WebMessageReceived += OnMessage;
                webReady = true;
                if (origin != null) web.CoreWebView2.Navigate(origin + "/quick");
            }
            catch (Exception error)
            {
                Log.Error("WebView2", error);
                ShowNotice("Wizard needs the Microsoft Edge WebView2 runtime, which ships with Windows 10 and 11 and Microsoft Edge. "
                           + "Ask IT to install it, then restart Wizard.\r\n\r\n" + error.Message, true);
            }
        }

        /// <summary>The service is ready on this address: load the compact view if it is not loaded yet.</summary>
        public void ServiceReady(string baseUrl)
        {
            var changed = origin != baseUrl;
            origin = baseUrl;
            if (!webReady) return;
            if (changed || !loaded || notice.Visible) web.CoreWebView2.Navigate(origin + "/quick");
        }

        public void ServiceProblem(string message, bool failed)
        {
            if (loaded && !failed) return;  // the page stays usable while the service restarts
            ShowNotice(message, failed);
        }

        private void ShowNotice(string message, bool actions)
        {
            noticeText.Text = message;
            retry.Visible = actions;
            logs.Visible = actions;
            notice.Visible = true;
            notice.BringToFront();
        }

        private void OnMessage(object sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            try
            {
                var message = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(e.WebMessageAsJson);
                var type = message != null && message.TryGetValue("type", out var t) ? t as string : null;
                if (type == "hide") HidePanel();
                else if (type == "busy") BusyChanged?.Invoke(message.TryGetValue("busy", out var b) && b is bool busy && busy);
                else if (type == "finished")
                    Finished?.Invoke(message.TryGetValue("question", out var q) ? q as string ?? "" : "",
                                     message.TryGetValue("ok", out var ok) && ok is bool done && done);
            }
            catch (Exception error) { Log.Error("web message", error); }
        }

        private static void OpenExternal(string uri)
        {
            if (!Uri.TryCreate(uri, UriKind.Absolute, out var parsed) || (parsed.Scheme != Uri.UriSchemeHttps && parsed.Scheme != Uri.UriSchemeHttp))
                return;
            try { Process.Start(new ProcessStartInfo(parsed.AbsoluteUri) { UseShellExecute = true }); }
            catch (Exception error) { Log.Error("open link", error); }
        }

        public static void OpenFolder(string folder)
        {
            try { Process.Start(new ProcessStartInfo("explorer.exe", "\"" + folder + "\"") { UseShellExecute = true }); }
            catch (Exception error) { Log.Error("open folder", error); }
        }

        public bool IsInFront => Visible && Native.GetForegroundWindow() == Handle;

        /// <summary>Show the panel under the button (or near the top of the screen when the button is hidden).</summary>
        public void ShowUnder(Rectangle button, bool buttonVisible)
        {
            var scale = IsHandleCreated ? Native.Scale(Handle) : 1f;
            var area = Screen.FromRectangle(button).WorkingArea;
            var width = settings.PanelWidth > 0 ? settings.PanelWidth : (int)Math.Min(760 * scale, area.Width * 0.5);
            var height = settings.PanelHeight > 0 ? settings.PanelHeight : (int)Math.Min(700 * scale, area.Height * 0.75);
            width = Math.Max(MinimumSize.Width, Math.Min(width, area.Width));
            height = Math.Max(MinimumSize.Height, Math.Min(height, area.Height));
            var center = buttonVisible ? button.Left + button.Width / 2 : area.Left + area.Width / 2;
            var left = Math.Max(area.Left, Math.Min(area.Right - width, center - width / 2));
            var top = buttonVisible ? Math.Max(area.Top, button.Bottom + (int)(4 * scale)) : area.Top + (int)(24 * scale);
            top = Math.Min(top, area.Bottom - height);
            Bounds = new Rectangle(left, top, width, height);
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Show();
            Activate();
            Native.SetForegroundWindow(Handle);
            if (webReady)
            {
                web.Focus();
                try { web.CoreWebView2.PostWebMessageAsJson("{\"type\":\"focus\"}"); } catch (Exception) { }
            }
        }

        public void HidePanel()
        {
            if (!Visible) return;
            Hide();
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Escape && notice.Visible) { HidePanel(); e.Handled = true; }
            base.OnKeyDown(e);
        }

        protected override void OnResizeEnd(EventArgs e)
        {
            base.OnResizeEnd(e);
            settings.PanelWidth = Width;
            settings.PanelHeight = Height;
            settings.Save();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            using (var pen = new Pen(Color.FromArgb(214, 211, 204))) e.Graphics.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
        }

        /// <summary>Resizable from its edges although it has no frame: the outer pixels answer as borders.</summary>
        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if (m.Msg != Native.WM_NCHITTEST || (int)m.Result != Native.HTCLIENT) return;
            var cursor = PointToClient(new Point(unchecked((short)(long)m.LParam), unchecked((short)((long)m.LParam >> 16))));
            var grip = (int)(Grip * Native.Scale(Handle));
            bool left = cursor.X < grip, right = cursor.X >= Width - grip, top = cursor.Y < grip, bottom = cursor.Y >= Height - grip;
            if (top && left) m.Result = (IntPtr)Native.HTTOPLEFT;
            else if (top && right) m.Result = (IntPtr)Native.HTTOPRIGHT;
            else if (bottom && left) m.Result = (IntPtr)Native.HTBOTTOMLEFT;
            else if (bottom && right) m.Result = (IntPtr)Native.HTBOTTOMRIGHT;
            else if (left) m.Result = (IntPtr)Native.HTLEFT;
            else if (right) m.Result = (IntPtr)Native.HTRIGHT;
            else if (top) m.Result = (IntPtr)Native.HTTOP;
            else if (bottom) m.Result = (IntPtr)Native.HTBOTTOM;
        }

        public void PrepareExit() => exiting = true;

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (!exiting && e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; HidePanel(); return; }
            base.OnFormClosing(e);
        }
    }
}
