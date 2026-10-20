using System;
using System.Threading;
using System.Windows.Forms;

namespace WizardBar
{
    internal static class Program
    {
        /// <summary>WizardBar [--install folder] [--home folder]. One instance per Windows session: a second start asks the
        /// running one to open its panel and exits.</summary>
        [STAThread]
        private static int Main(string[] args)
        {
            using (var single = new Mutex(true, @"Local\WizardBar", out var first))
            using (var open = new EventWaitHandle(false, EventResetMode.AutoReset, @"Local\WizardBar.Open"))
            {
                if (!first)
                {
                    open.Set();
                    return 0;
                }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                var paths = Paths.FromArguments(args);
                Log.Init(paths);
                Application.ThreadException += (s, e) => Log.Error("UI", e.Exception);
                AppDomain.CurrentDomain.UnhandledException += (s, e) => Log.Write("FATAL " + e.ExceptionObject);
                using (var context = new WizardContext(paths))
                {
                    // A second launch (Start menu, desktop shortcut) opens the panel of this one.
                    ThreadPool.RegisterWaitForSingleObject(open, (state, timedOut) => context.OpenFromAnotherLaunch(), null, -1, false);
                    Application.Run(context);
                }
                return 0;
            }
        }
    }
}
