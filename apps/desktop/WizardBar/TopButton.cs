using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace WizardBar
{
    internal enum ButtonLook { Starting, Ready, Working, Answered, Failed }

    /// <summary>The always-on button: a tab hanging from the top edge of the main screen with the pixel wizard in it. He
    /// rests (and twinkles his staff now and then), drops down and waves when the pointer is on the tab, casts when it is
    /// clicked, acts out what Wizard is doing while a question runs (the page tells: reading, searching, writing...), hops
    /// when the answer is ready and fizzles when the service stopped. A file dragged onto the tab is attached to the
    /// conversation. It stays above other windows, never takes the keyboard focus, steps aside for full-screen apps and
    /// slide shows, and can be dragged along the top edge.</summary>
    internal sealed class TopButton : Form
    {
        private static readonly Color Blue = Color.FromArgb(255, 20, 40, 160);       // Samsung Blue, as the wizard's robe
        private static readonly Color BlueLight = Color.FromArgb(255, 58, 92, 214);
        private static readonly Color Green = Color.FromArgb(255, 52, 199, 89);
        private const double IdleEvery = 9;  // seconds between the resting wizard's staff twinkles
        private readonly BarSettings settings;
        private readonly Timer keeper = new Timer { Interval = 1000 };
        private readonly Timer frames = new Timer { Interval = 250 };
        private readonly Stopwatch clock = Stopwatch.StartNew();
        private ButtonLook look = ButtonLook.Starting;
        private string activity;
        private bool hover, pressed, dragging, fileOver, hiddenForFullScreen;
        private Point pressAt;
        private int pressLeft;
        private string playing = "think";
        private double playingSince, castUntil = -1;
        private double lift, grow;  // 0..1, eased: the tab drops down on hover, and further for a file
        private string drawn;       // what the last frame showed, so a tick that changes nothing draws nothing

        public event Action Clicked;
        /// <summary>Files dragged onto the button: raised during the drop, while the dragged data can still be read.</summary>
        public event Action<IDataObject> FilesDropped;
        public ContextMenuStrip RightClickMenu { get; set; }

        public TopButton(BarSettings settings)
        {
            this.settings = settings;
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            TopMost = true;
            Text = "Wizard";
            AllowDrop = true;
            keeper.Tick += (s, e) => Keep();
            frames.Tick += (s, e) => Tick();
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
            Tick();
            keeper.Start();
            frames.Start();
        }

        protected override void OnHandleDestroyed(EventArgs e)
        {
            Microsoft.Win32.SystemEvents.DisplaySettingsChanged -= OnDisplayChanged;
            base.OnHandleDestroyed(e);
        }

        private void OnDisplayChanged(object sender, EventArgs e) => BeginInvoke((Action)(() => { drawn = null; Tick(); }));

        public ButtonLook Look
        {
            get => look;
            set
            {
                if (look == value) return;
                look = value;
                Tick();
            }
        }

        /// <summary>What the wizard on the page acts out while a question runs (apps/web/src/wizard.ts).</summary>
        public string Activity
        {
            set
            {
                activity = value;
                if (look == ButtonLook.Working) Tick();
            }
        }

        private string Caption => fileOver ? "Drop to attach" : look switch
        {
            ButtonLook.Starting => "Starting Wizard…",
            ButtonLook.Working => "Wizard is working…",
            ButtonLook.Answered => "Wizard answered",
            ButtonLook.Failed => "Wizard stopped",
            _ => "Ask Wizard",
        };

        /// <summary>The second line, shown while the tab is dropped down.</summary>
        private string Hint => fileOver ? "Wizard reads it with your question" : look switch
        {
            ButtonLook.Starting => "One moment",
            ButtonLook.Working => "Click to watch",
            ButtonLook.Answered => "Click to read it",
            ButtonLook.Failed => "Click for the reason",
            _ => "Click, Ctrl+Alt+W, or drop a file",
        };

        private double Now => clock.Elapsed.TotalSeconds;

        private string Wanted()
        {
            if (fileOver) return "read";
            if (Now < castUntil) return "cast";
            switch (look)
            {
                case ButtonLook.Starting: return "think";
                case ButtonLook.Failed: return "fail";
                case ButtonLook.Answered: return "success";
                case ButtonLook.Working:
                    return activity != null && activity != "success" && activity != "fail" && activity != "idle"
                        && SpriteSheet.Animations.ContainsKey(activity) ? activity : "cast";
            }
            return hover ? "wave" : "idle";
        }

        private int Frame(double now)
        {
            var animation = SpriteSheet.Get(playing);
            var t = now - playingSince;
            if (playing != "idle") return animation.FrameAt(t);
            var cycle = t % IdleEvery;
            return cycle < animation.Seconds ? animation.FrameAt(cycle) : 0;
        }

        private static double Ease(double value, double target)
        {
            var next = value + (target - value) * 0.28;
            return Math.Abs(target - next) < 0.01 ? target : next;
        }

        /// <summary>One step of the animation: picks what the wizard acts out, eases the tab, draws when something changed,
        /// and sets how soon the next step is due (often while something moves, rarely while he rests).</summary>
        private void Tick()
        {
            if (!IsHandleCreated) return;
            var now = Now;
            var want = Wanted();
            if (want != playing) { playing = want; playingSince = now; }
            double liftTarget = hover || pressed || fileOver ? 1 : 0, growTarget = fileOver ? 1 : 0;
            lift = Ease(lift, liftTarget);
            grow = Ease(grow, growTarget);
            if (Visible) Render(now);
            var animation = SpriteSheet.Get(playing);
            var t = now - playingSince;
            var still = playing == "idle" ? t % IdleEvery >= animation.Seconds : !animation.Loop && t >= animation.Seconds;
            var interval = lift != liftTarget || grow != growTarget ? 16
                : look == ButtonLook.Working ? 40
                : !still ? Math.Max(30, 500 / animation.Fps)
                : look == ButtonLook.Answered ? 120
                : 250;
            if (frames.Interval != interval) frames.Interval = interval;
        }

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
            if (settings.ShowButton && !hiddenForFullScreen) { Show(); drawn = null; Tick(); } else Hide();
        }

        private void Render(double now)
        {
            var scale = Native.Scale(Handle);
            var screen = Screen.PrimaryScreen.WorkingArea;
            var pose = new Pose
            {
                Look = look, Animation = playing, Frame = Frame(now), Caption = Caption, Hint = Hint, Lift = lift, Grow = grow,
                Pressed = pressed, FileOver = fileOver, Scale = scale,
                Shimmer = look == ButtonLook.Working ? now % 1.4 / 1.4 : -1,
                Pulse = look == ButtonLook.Answered ? (int)(now * 8) % 16 : -1,
            };
            var key = pose.Key + "|" + (dragging ? Left : -1) + "|" + settings.ButtonX + "|" + screen;
            if (key == drawn) return;
            drawn = key;
            using (var bitmap = Picture(pose))
            {
                var left = Left;
                if (!dragging)
                {
                    var center = screen.Left + (int)(settings.ButtonX * screen.Width);
                    left = Math.Max(screen.Left, Math.Min(screen.Right - bitmap.Width, center - bitmap.Width / 2));
                }
                Present(bitmap, left, screen.Top);
            }
        }

        /// <summary>Everything one picture of the button depends on.</summary>
        internal struct Pose
        {
            public ButtonLook Look;
            public string Animation, Caption, Hint;
            public int Frame, Pulse;
            public double Lift, Grow, Shimmer;
            public bool Pressed, FileOver;
            public float Scale;

            public string Key => string.Join("|", Look, Animation, Frame, Caption, Hint, (int)(Lift * 24), (int)(Grow * 24),
                Pressed, FileOver, Shimmer < 0 ? -1 : (int)(Shimmer * 48), Pulse, Scale);
        }

        /// <summary>The button as a picture with per-pixel transparency: the tab, its shadow or glow, the wizard, the words.</summary>
        internal static Bitmap Picture(Pose p)
        {
            var scale = p.Scale;
            // Pixel art only scales by whole numbers: 1x up to 150 % display scaling, 2x from 175 %.
            var px = Math.Max(1, (int)Math.Floor(scale + 0.25));
            var show = Math.Max(p.Lift, p.Grow);
            using (var font = new Font("Segoe UI Semibold", 12.5f * scale, FontStyle.Regular, GraphicsUnit.Pixel))
            using (var small = new Font("Segoe UI", 10.5f * scale, FontStyle.Regular, GraphicsUnit.Pixel))
            {
                var captionWidth = TextRenderer.MeasureText(p.Caption, font).Width;
                var hintWidth = TextRenderer.MeasureText(p.Hint, small).Width;
                var textWidth = (int)Math.Round(captionWidth + Math.Max(0, hintWidth - captionWidth) * show);
                var shadow = (int)Math.Round(7 * scale);
                var height = (int)Math.Round(40 * px + 2 * scale + 8 * scale * p.Lift + 14 * scale * p.Grow);
                var spriteWidth = 37 * px;  // the wizard and his staff: columns 7 to 43 of the 48-pixel frame
                var badge = p.Pulse >= 0 ? 14 * scale : 0;  // room for the "answer waiting" dot after the caption
                var width = (int)Math.Round(6 * scale + spriteWidth + 8 * scale + textWidth + badge + 16 * scale);
                var bitmap = new Bitmap(width + 2 * shadow, height + shadow, PixelFormat.Format32bppArgb);
                using (var g = Graphics.FromImage(bitmap))
                {
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                    g.Clear(Color.Transparent);
                    var radius = 13f * scale;
                    var body = new RectangleF(shadow, -1, width, height);
                    // Soft shadow; with the pointer on the tab, a blue glow.
                    for (var i = shadow; i > 0; i--)
                    {
                        using (var path = Tab(new RectangleF(shadow - i, -1, width + 2 * i, height + i), radius + i))
                        using (var brush = new SolidBrush(p.Lift > 0
                            ? Color.FromArgb((int)(Math.Max(1, 26 - 3.5 * i) * (1 + 1.4 * p.Lift)), 58, 92, 214)
                            : Color.FromArgb(Math.Max(1, 24 - 3 * i), 8, 14, 60)))
                            g.FillPath(brush, path);
                    }
                    using (var path = Tab(body, radius))
                    {
                        var top = p.Pressed ? Color.FromArgb(255, 232, 237, 251) : p.FileOver ? Color.FromArgb(255, 238, 243, 255) : Color.White;
                        var bottom = p.Pressed ? Color.FromArgb(255, 220, 228, 250) : Color.FromArgb(255, 236, 241, 252);
                        using (var brush = new LinearGradientBrush(new RectangleF(body.X, body.Y, body.Width, body.Height + 1), top, bottom, LinearGradientMode.Vertical))
                            g.FillPath(brush, path);
                        var state = g.Save();
                        g.SetClip(path);
                        SpriteSheet.Draw(g, p.Animation, p.Frame, body.X + 6 * scale - 7 * px, body.Bottom - 2 * scale - SpriteSheet.Frame * px, px);
                        if (p.Shimmer >= 0)
                        {
                            // A question is running: a glint runs along the bottom edge.
                            var bar = new RectangleF(body.X, body.Bottom - 3 * scale, body.Width, 3 * scale);
                            using (var track = new SolidBrush(Color.FromArgb(50, BlueLight))) g.FillRectangle(track, bar);
                            var span = body.Width * 0.38f;
                            var glint = new RectangleF(body.X - span + (body.Width + span) * (float)p.Shimmer, bar.Y, span, bar.Height);
                            using (var brush = new LinearGradientBrush(new RectangleF(glint.X - 1, glint.Y, glint.Width + 2, glint.Height), BlueLight, BlueLight, LinearGradientMode.Horizontal))
                            {
                                brush.InterpolationColors = new ColorBlend
                                {
                                    Colors = new[] { Color.FromArgb(0, BlueLight), BlueLight, Color.FromArgb(0, BlueLight) },
                                    Positions = new[] { 0f, 0.5f, 1f },
                                };
                                g.FillRectangle(brush, glint);
                            }
                        }
                        g.Restore(state);
                        using (var pen = p.FileOver
                            ? new Pen(BlueLight, 1.8f * scale) { DashStyle = DashStyle.Dash }
                            : new Pen(p.Lift > 0 ? Color.FromArgb((int)(90 + 140 * p.Lift), BlueLight) : Color.FromArgb(255, 201, 211, 238), (1f + 0.5f * (float)p.Lift) * scale))
                            g.DrawPath(pen, path);
                    }
                    var textX = body.X + 6 * scale + spriteWidth + 8 * scale;
                    var lineOne = font.GetHeight(g);
                    var lineTwo = small.GetHeight(g) * (float)show;
                    var textY = (height - 1 - lineOne - lineTwo) / 2f - 1;
                    var captionColor = p.Look == ButtonLook.Failed ? Color.FromArgb(255, 190, 30, 30) : Blue;
                    if (p.Pulse >= 0)
                    {
                        // An answer is waiting: a green dot after the caption, gently pulsing.
                        var dot = (7f + (p.Pulse < 8 ? p.Pulse : 16 - p.Pulse) * 0.2f) * scale;
                        var cx = textX + captionWidth + 8 * scale;
                        var cy = textY + lineOne / 2 + 1 * scale;
                        using (var brush = new SolidBrush(Green)) g.FillEllipse(brush, cx - dot / 2, cy - dot / 2, dot, dot);
                        using (var pen = new Pen(Color.FromArgb(120, Green), 1.2f * scale))
                            g.DrawEllipse(pen, cx - dot / 2 - 2 * scale, cy - dot / 2 - 2 * scale, dot + 4 * scale, dot + 4 * scale);
                    }
                    using (var text = new SolidBrush(Color.FromArgb(p.Look == ButtonLook.Starting ? 170 : 255, captionColor)))
                    using (var format = new StringFormat { FormatFlags = StringFormatFlags.NoWrap, Trimming = StringTrimming.None })
                    {
                        g.DrawString(p.Caption, font, text, textX, textY, format);
                        if (show > 0.05)
                            using (var faint = new SolidBrush(Color.FromArgb((int)(220 * show), 74, 82, 110)))
                                g.DrawString(p.Hint, small, faint, textX + 0.5f * scale, textY + lineOne, format);
                    }
                }
                return bitmap;
            }
        }

        /// <summary>WizardBar --snapshot FOLDER: every look of the button at 100 % and 200 % on a light and a dark title bar,
        /// as one PNG (CI runs it, to see the button without a desktop). False when the sprite sheet is missing.</summary>
        public static bool Snapshot(string folder)
        {
            if (!SpriteSheet.Available) return false;
            var poses = new (string name, ButtonLook look, string animation, int frame, string caption, string hint, double lift, double grow, bool pressed, bool fileOver, double shimmer, int pulse)[]
            {
                ("rest", ButtonLook.Ready, "idle", 0, "Ask Wizard", "Click, Ctrl+Alt+W, or drop a file", 0, 0, false, false, -1, -1),
                ("hover", ButtonLook.Ready, "wave", 2, "Ask Wizard", "Click, Ctrl+Alt+W, or drop a file", 1, 0, false, false, -1, -1),
                ("click", ButtonLook.Ready, "cast", 3, "Ask Wizard", "Click, Ctrl+Alt+W, or drop a file", 1, 0, true, false, -1, -1),
                ("file", ButtonLook.Ready, "read", 2, "Drop to attach", "Wizard reads it with your question", 1, 1, false, true, -1, -1),
                ("starting", ButtonLook.Starting, "think", 3, "Starting Wizard…", "One moment", 0, 0, false, false, -1, -1),
                ("working", ButtonLook.Working, "read", 1, "Wizard is working…", "Click to watch", 0, 0, false, false, 0.45, -1),
                ("answered", ButtonLook.Answered, "success", 7, "Wizard answered", "Click to read it", 0, 0, false, false, -1, 4),
                ("failed", ButtonLook.Failed, "fail", 5, "Wizard stopped", "Click for the reason", 0, 0, false, false, -1, -1),
            };
            Directory.CreateDirectory(folder);
            foreach (var scale in new[] { 1f, 2f })
            {
                var pictures = new System.Collections.Generic.List<Bitmap>();
                foreach (var q in poses)
                    pictures.Add(Picture(new Pose
                    {
                        Look = q.look, Animation = q.animation, Frame = q.frame, Caption = q.caption, Hint = q.hint, Lift = q.lift, Grow = q.grow,
                        Pressed = q.pressed, FileOver = q.fileOver, Shimmer = q.shimmer, Pulse = q.pulse, Scale = scale,
                    }));
                var cell = new Size(pictures.Max(b => b.Width) + (int)(16 * scale), pictures.Max(b => b.Height) + (int)(12 * scale));
                using (var sheet = new Bitmap(cell.Width * 2, cell.Height * pictures.Count, PixelFormat.Format32bppArgb))
                using (var g = Graphics.FromImage(sheet))
                {
                    for (var i = 0; i < pictures.Count; i++)
                    {
                        // Left: a light (Windows 11) title bar; right: a dark one.
                        using (var light = new SolidBrush(Color.FromArgb(255, 243, 243, 243))) g.FillRectangle(light, 0, i * cell.Height, cell.Width, cell.Height);
                        using (var dark = new SolidBrush(Color.FromArgb(255, 32, 32, 32))) g.FillRectangle(dark, cell.Width, i * cell.Height, cell.Width, cell.Height);
                        g.DrawImage(pictures[i], (cell.Width - pictures[i].Width) / 2, i * cell.Height);
                        g.DrawImage(pictures[i], cell.Width + (cell.Width - pictures[i].Width) / 2, i * cell.Height);
                        pictures[i].Dispose();
                    }
                    sheet.Save(Path.Combine(folder, "button-" + (int)(scale * 100) + ".png"), ImageFormat.Png);
                }
            }
            return true;
        }

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

        protected override void OnMouseEnter(EventArgs e) { hover = true; Tick(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; pressed = false; Tick(); base.OnMouseLeave(e); }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Left)
            {
                pressed = true;
                pressAt = Cursor.Position;
                pressLeft = Left;
                Tick();
            }
            base.OnMouseDown(e);
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            if (pressed && (dragging || Math.Abs(Cursor.Position.X - pressAt.X) > SystemInformation.DragSize.Width))
            {
                dragging = true;
                var screen = Screen.PrimaryScreen.WorkingArea;
                Left = Math.Max(screen.Left, Math.Min(screen.Right - Width, pressLeft + Cursor.Position.X - pressAt.X));
                Tick();
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
            else if (e.Button == MouseButtons.Left)
            {
                castUntil = Now + SpriteSheet.Get("cast").Seconds;
                Clicked?.Invoke();
            }
            Tick();
            base.OnMouseUp(e);
        }

        protected override void OnDragEnter(DragEventArgs e)
        {
            fileOver = Dropped.HasFiles(e.Data);
            e.Effect = fileOver ? DragDropEffects.Copy : DragDropEffects.None;
            Tick();
            base.OnDragEnter(e);
        }

        protected override void OnDragOver(DragEventArgs e)
        {
            e.Effect = fileOver ? DragDropEffects.Copy : DragDropEffects.None;
            base.OnDragOver(e);
        }

        protected override void OnDragLeave(EventArgs e)
        {
            fileOver = false;
            Tick();
            base.OnDragLeave(e);
        }

        protected override void OnDragDrop(DragEventArgs e)
        {
            fileOver = false;
            castUntil = Now + SpriteSheet.Get("cast").Seconds;
            Tick();
            try { FilesDropped?.Invoke(e.Data); }
            catch (Exception error) { Log.Error("drop", error); }
            base.OnDragDrop(e);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) { keeper.Dispose(); frames.Dispose(); }
            base.Dispose(disposing);
        }
    }
}
