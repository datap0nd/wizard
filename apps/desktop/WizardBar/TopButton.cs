using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.Windows.Forms;

namespace WizardBar
{
    internal enum ButtonLook { Starting, Ready, Working, Answered, Failed }

    /// <summary>The always-on button: a small tab hanging from the top edge of the main screen. It stays above other
    /// windows, never takes the keyboard focus, steps aside for full-screen apps and slide shows, and can be dragged
    /// along the top edge. A click opens or hides the panel; a right-click opens the menu.</summary>
    internal sealed class TopButton : Form
    {
        private static readonly Color Accent = Color.FromArgb(255, 61, 90, 254);
        private readonly BarSettings settings;
        private readonly Timer keeper = new Timer { Interval = 1000 };
        private readonly Timer pulse = new Timer { Interval = 80 };
        private ButtonLook look = ButtonLook.Starting;
        private bool hover, pressed, dragging, hiddenForFullScreen;
        private Point pressAt;
        private int pressLeft;
        private float phase;

        public event Action Clicked;
        public ContextMenuStrip RightClickMenu { get; set; }

        public TopButton(BarSettings settings)
        {
            this.settings = settings;
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            TopMost = true;
            Text = "Wizard";
            keeper.Tick += (s, e) => Keep();
            pulse.Tick += (s, e) => { phase = (phase + 0.08f) % 1f; Render(); };
        }

        protected override CreateParams CreateParams
        {
            get
            {
                var p = base.CreateParams;
                p.ExStyle |= Native.WS_EX_LAYERED | Native.WS_EX_TOOLWINDOW | Native.WS_EX_TOPMOST | Native.WS_EX_NOACTIVATE;
                return p;
            }
        }

        protected override bool ShowWithoutActivation => true;

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == Native.WM_MOUSEACTIVATE) { m.Result = (IntPtr)Native.MA_NOACTIVATE; return; }
            base.WndProc(ref m);
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            Microsoft.Win32.SystemEvents.DisplaySettingsChanged += OnDisplayChanged;
            Render();
            keeper.Start();
        }

        protected override void OnHandleDestroyed(EventArgs e)
        {
            Microsoft.Win32.SystemEvents.DisplaySettingsChanged -= OnDisplayChanged;
            base.OnHandleDestroyed(e);
        }

        private void OnDisplayChanged(object sender, EventArgs e) => BeginInvoke((Action)Render);

        public ButtonLook Look
        {
            get => look;
            set
            {
                if (look == value) return;
                look = value;
                if (look == ButtonLook.Working || look == ButtonLook.Starting) pulse.Start(); else pulse.Stop();
                Render();
            }
        }

        private string Caption => look switch
        {
            ButtonLook.Starting => "Starting Wizard…",
            ButtonLook.Working => "Wizard is working…",
            ButtonLook.Answered => "Wizard answered",
            ButtonLook.Failed => "Wizard stopped",
            _ => "Ask Wizard",
        };

        /// <summary>Keeps the button on top of other topmost windows and out of the way of full-screen apps.</summary>
        private void Keep()
        {
            var full = Native.FullScreenAppInFront();
            if (full != hiddenForFullScreen)
            {
                hiddenForFullScreen = full;
                if (full) Hide(); else if (settings.ShowButton) Show();
            }
            if (Visible) Native.SetWindowPos(Handle, Native.HWND_TOPMOST, 0, 0, 0, 0,
                Native.SWP_NOMOVE | Native.SWP_NOSIZE | Native.SWP_NOACTIVATE);
        }

        public void ApplyVisibility()
        {
            if (settings.ShowButton && !hiddenForFullScreen) { Show(); Render(); } else Hide();
        }

        private void Render()
        {
            if (!IsHandleCreated) return;
            var scale = Native.Scale(Handle);
            var screen = Screen.PrimaryScreen.WorkingArea;
            using (var font = new Font("Segoe UI Semibold", 9.5f * scale, FontStyle.Regular, GraphicsUnit.Pixel))
            {
                var caption = Caption;
                var textWidth = TextRenderer.MeasureText(caption, font).Width;
                var height = (int)Math.Round(30 * scale);
                var width = (int)Math.Round(46 * scale) + textWidth;
                var shadow = (int)Math.Round(6 * scale);
                var fullWidth = width + 2 * shadow;
                var fullHeight = height + shadow;
                int left;
                if (dragging) left = Left;
                else
                {
                    var center = screen.Left + (int)(settings.ButtonX * screen.Width);
                    left = Math.Max(screen.Left, Math.Min(screen.Right - fullWidth, center - fullWidth / 2));
                }
                using (var bitmap = new Bitmap(fullWidth, fullHeight, PixelFormat.Format32bppArgb))
                {
                    using (var g = Graphics.FromImage(bitmap))
                    {
                        g.SmoothingMode = SmoothingMode.AntiAlias;
                        g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                        g.Clear(Color.Transparent);
                        var radius = 11f * scale;
                        for (var i = shadow; i > 0; i--)
                        {
                            using (var path = Tab(new RectangleF(shadow - i, -1, width + 2 * i, height + i), radius + i))
                            using (var brush = new SolidBrush(Color.FromArgb(Math.Max(1, 22 - 3 * i), 0, 0, 0)))
                                g.FillPath(brush, path);
                        }
                        var body = new RectangleF(shadow, -1, width, height);
                        using (var path = Tab(body, radius))
                        {
                            var fill = pressed ? Color.FromArgb(250, 44, 46, 52) : hover ? Color.FromArgb(250, 52, 55, 62) : Color.FromArgb(242, 32, 33, 38);
                            using (var brush = new SolidBrush(fill)) g.FillPath(brush, path);
                            using (var pen = new Pen(Color.FromArgb(40, 255, 255, 255), 1f)) g.DrawPath(pen, path);
                        }
                        var badge = 18f * scale;
                        var badgeRect = new RectangleF(shadow + 8 * scale, (height - badge) / 2f - 0.5f, badge, badge);
                        using (var brush = new SolidBrush(BadgeColor())) g.FillEllipse(brush, badgeRect);
                        using (var glyph = new Font("Segoe UI", 10f * scale, FontStyle.Bold, GraphicsUnit.Pixel))
                        using (var format = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center })
                            g.DrawString("W", glyph, Brushes.White, new RectangleF(badgeRect.X, badgeRect.Y + 0.5f * scale, badgeRect.Width, badgeRect.Height), format);
                        if (look == ButtonLook.Working || look == ButtonLook.Starting)
                        {
                            using (var pen = new Pen(Color.FromArgb(230, 255, 255, 255), 1.8f * scale))
                            {
                                var ring = RectangleF.Inflate(badgeRect, 2.5f * scale, 2.5f * scale);
                                g.DrawArc(pen, ring, phase * 360f, 100f);
                            }
                        }
                        using (var text = new SolidBrush(Color.FromArgb(look == ButtonLook.Starting ? 190 : 245, 255, 255, 255)))
                        using (var format = new StringFormat { LineAlignment = StringAlignment.Center, FormatFlags = StringFormatFlags.NoWrap })
                            g.DrawString(caption, font, text, new RectangleF(badgeRect.Right + 8 * scale, 0, textWidth + 8 * scale, height - 1), format);
                        if (look == ButtonLook.Answered)
                        {
                            var dot = 7f * scale;
                            using (var brush = new SolidBrush(Color.FromArgb(255, 52, 199, 89)))
                                g.FillEllipse(brush, badgeRect.Right - dot + 1.5f * scale, badgeRect.Top - 1.5f * scale, dot, dot);
                        }
                    }
                    Present(bitmap, left, screen.Top);
                }
            }
        }

        private Color BadgeColor() => look switch
        {
            ButtonLook.Failed => Color.FromArgb(255, 220, 64, 64),
            ButtonLook.Answered => Color.FromArgb(255, 36, 160, 92),
            _ => Accent,
        };

        /// <summary>A rectangle with a square top (it touches the screen edge) and rounded bottom corners.</summary>
        private static GraphicsPath Tab(RectangleF r, float radius)
        {
            var path = new GraphicsPath();
            var d = Math.Min(radius * 2, Math.Min(r.Width, r.Height));
            path.AddLine(r.Left, r.Top, r.Right, r.Top);
            path.AddLine(r.Right, r.Top, r.Right, r.Bottom - d / 2);
            path.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            path.AddLine(r.Right - d / 2, r.Bottom, r.Left + d / 2, r.Bottom);
            path.AddArc(r.Left, r.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }

        private void Present(Bitmap bitmap, int left, int top)
        {
            var screenDc = Native.GetDC(IntPtr.Zero);
            var memoryDc = Native.CreateCompatibleDC(screenDc);
            var hBitmap = bitmap.GetHbitmap(Color.FromArgb(0));
            var previous = Native.SelectObject(memoryDc, hBitmap);
            try
            {
                var size = new Native.SIZE(bitmap.Width, bitmap.Height);
                var source = new Native.POINT(0, 0);
                var destination = new Native.POINT(left, top);
                var blend = new Native.BLENDFUNCTION { BlendOp = Native.AC_SRC_OVER, SourceConstantAlpha = 255, AlphaFormat = Native.AC_SRC_ALPHA };
                Native.UpdateLayeredWindow(Handle, screenDc, ref destination, ref size, memoryDc, ref source, 0, ref blend, Native.ULW_ALPHA);
                SetBounds(left, top, bitmap.Width, bitmap.Height, BoundsSpecified.All);
            }
            finally
            {
                Native.SelectObject(memoryDc, previous);
                Native.DeleteObject(hBitmap);
                Native.DeleteDC(memoryDc);
                Native.ReleaseDC(IntPtr.Zero, screenDc);
            }
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Render(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; pressed = false; Render(); base.OnMouseLeave(e); }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Left)
            {
                pressed = true;
                pressAt = Cursor.Position;
                pressLeft = Left;
                Render();
            }
            base.OnMouseDown(e);
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            if (pressed && (dragging || Math.Abs(Cursor.Position.X - pressAt.X) > SystemInformation.DragSize.Width))
            {
                dragging = true;
                var screen = Screen.PrimaryScreen.WorkingArea;
                var left = Math.Max(screen.Left, Math.Min(screen.Right - Width, pressLeft + Cursor.Position.X - pressAt.X));
                Left = left;
                Render();
            }
            base.OnMouseMove(e);
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            var wasDragging = dragging;
            pressed = false;
            dragging = false;
            if (e.Button == MouseButtons.Right && RightClickMenu != null)
            {
                // As NotifyIcon does: a menu from a window that never takes the focus closes on an outside click only
                // when it is the foreground window.
                RightClickMenu.Show(this, new Point(e.X, Height));
                Native.SetForegroundWindow(RightClickMenu.Handle);
            }
            else if (wasDragging)
            {
                var screen = Screen.PrimaryScreen.WorkingArea;
                settings.ButtonX = Math.Max(0, Math.Min(1, (Left + Width / 2.0 - screen.Left) / screen.Width));
                settings.Save();
            }
            else if (e.Button == MouseButtons.Left) Clicked?.Invoke();
            Render();
            base.OnMouseUp(e);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) { keeper.Dispose(); pulse.Dispose(); }
            base.Dispose(disposing);
        }
    }
}
