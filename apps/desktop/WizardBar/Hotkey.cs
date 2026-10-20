using System;
using System.Windows.Forms;

namespace WizardBar
{
    /// <summary>Ctrl+Alt+W from any app shows or hides the panel. If another program already owns the combination, the
    /// button and the tray icon still work and the log says so.</summary>
    internal sealed class Hotkey : NativeWindow, IDisposable
    {
        private const int Id = 0x5749;  // "WI"
        public event Action Pressed;
        public bool Registered { get; }

        public Hotkey()
        {
            CreateHandle(new CreateParams());
            Registered = Native.RegisterHotKey(Handle, Id, Native.MOD_CONTROL | Native.MOD_ALT | Native.MOD_NOREPEAT, (uint)Keys.W);
            Log.Write(Registered ? "hotkey Ctrl+Alt+W registered" : "hotkey Ctrl+Alt+W is taken by another program");
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == Native.WM_HOTKEY && (int)m.WParam == Id) Pressed?.Invoke();
            base.WndProc(ref m);
        }

        public void Dispose()
        {
            if (Registered) Native.UnregisterHotKey(Handle, Id);
            DestroyHandle();
        }
    }
}
