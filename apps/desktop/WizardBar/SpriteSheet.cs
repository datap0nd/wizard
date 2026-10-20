using System;
using System.Drawing;
using System.Drawing.Drawing2D;

namespace WizardBar
{
    /// <summary>One row of the sprite sheet: frames per second and whether it loops.</summary>
    internal readonly struct Animation
    {
        public readonly int Row, Frames, Fps;
        public readonly bool Loop;

        public Animation(int row, int frames, int fps, bool loop)
        {
            Row = row;
            Frames = frames;
            Fps = fps;
            Loop = loop;
        }

        public double Seconds => (double)Frames / Fps;

        /// <summary>The frame to show this long after the animation started; a one-shot stays on its last frame.</summary>
        public int FrameAt(double seconds)
        {
            var index = (int)(Math.Max(0, seconds) * Fps);
            return Loop ? index % Frames : Math.Min(index, Frames - 1);
        }
    }

    /// <summary>The pixel wizard, the same sheet the web app uses (scripts/wizard_art.py draws it and the animation table in
    /// SpriteSheet.g.cs). Embedded as WizardBar.wizard-sprite.png.</summary>
    internal static partial class SpriteSheet
    {
        private static Bitmap sheet;
        private static bool loaded;

        private static Bitmap Image
        {
            get
            {
                if (loaded) return sheet;
                loaded = true;
                try
                {
                    using (var stream = typeof(SpriteSheet).Assembly.GetManifestResourceStream("WizardBar.wizard-sprite.png"))
                    using (var decoded = stream != null ? new Bitmap(stream) : null)
                        if (decoded != null) sheet = new Bitmap(decoded);  // a copy: GDI+ reads a stream bitmap lazily
                }
                catch (Exception error) { Log.Error("sprite sheet", error); }
                return sheet;
            }
        }

        public static bool Available => Image != null;

        public static Animation Get(string name) => name != null && Animations.TryGetValue(name, out var found) ? found : Animations["idle"];

        /// <summary>Draws one frame, its top-left corner at (x, y), scaled by a whole number with hard pixel edges.</summary>
        public static void Draw(Graphics g, string animation, int frame, float x, float y, int scale)
        {
            var image = Image;
            if (image == null) return;
            var row = Get(animation).Row;
            var state = g.Save();
            g.InterpolationMode = InterpolationMode.NearestNeighbor;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            g.SmoothingMode = SmoothingMode.None;
            g.DrawImage(image, new RectangleF((float)Math.Round(x), (float)Math.Round(y), Frame * scale, Frame * scale),
                new RectangleF(frame * Frame, row * Frame, Frame, Frame), GraphicsUnit.Pixel);
            g.Restore(state);
        }
    }
}
