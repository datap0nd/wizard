using System;
using System.Drawing;
using System.Windows.Forms;

namespace WizardBar
{
    /// <summary>The Wizard icon (assets/wizard.ico, embedded) at the sizes Windows asks for.</summary>
    internal static class Icons
    {
        public static Icon App() => Load(SystemInformation.IconSize);

        public static Icon Tray() => Load(SystemInformation.SmallIconSize);

        private static Icon Load(Size size)
        {
            try
            {
                using (var stream = typeof(Icons).Assembly.GetManifestResourceStream("WizardBar.wizard.ico"))
                    if (stream != null) return new Icon(stream, size);
            }
            catch (Exception error) { Log.Error("icon", error); }
            return SystemIcons.Application;
        }
    }
}
