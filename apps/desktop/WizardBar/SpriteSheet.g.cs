// Drawn by scripts/wizard_art.py, which writes this file with the sprite sheet: do not edit by hand.
using System.Collections.Generic;

namespace WizardBar
{
    internal static partial class SpriteSheet
    {
        public const int Frame = 48;
        public static readonly Dictionary<string, Animation> Animations = new Dictionary<string, Animation>
        {
            { "idle", new Animation(0, 6, 6, true) },
            { "wave", new Animation(1, 6, 8, true) },
            { "think", new Animation(2, 6, 6, true) },
            { "search", new Animation(3, 6, 7, true) },
            { "read", new Animation(4, 6, 6, true) },
            { "write", new Animation(5, 6, 6, true) },
            { "cast", new Animation(6, 6, 8, true) },
            { "chart", new Animation(7, 6, 6, true) },
            { "check", new Animation(8, 6, 6, true) },
            { "success", new Animation(9, 8, 10, false) },
            { "fail", new Animation(10, 6, 7, false) },
        };
    }
}
