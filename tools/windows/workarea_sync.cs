// Synchronize Windows' current work areas through WSLg's existing RAIL channel.
// No application patch, fixed taskbar size, or system work-area setter is used.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace WslgRemake {
    internal static class Native {
        [StructLayout(LayoutKind.Sequential)] internal struct Rect {
            public int left, top, right, bottom;
            public override string ToString() { return String.Join(",", left, top, right, bottom); }
        }
        [StructLayout(LayoutKind.Sequential)] internal struct MonitorInfo {
            public int size; public Rect monitor, work; public uint flags;
        }
        internal delegate bool MonitorCallback(IntPtr monitor, IntPtr dc, IntPtr rect, IntPtr arg);
        internal delegate bool WindowCallback(IntPtr window, IntPtr arg);
        [DllImport("user32.dll")] internal static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
        [DllImport("user32.dll")] internal static extern bool SetProcessDpiAwarenessContext(IntPtr context);
        [DllImport("user32.dll")] internal static extern bool EnumDisplayMonitors(IntPtr dc, IntPtr clip, MonitorCallback callback, IntPtr arg);
        [DllImport("user32.dll")] internal static extern bool GetMonitorInfo(IntPtr monitor, ref MonitorInfo info);
        [DllImport("shcore.dll")] internal static extern int GetDpiForMonitor(IntPtr monitor, int type, out uint x, out uint y);
        [DllImport("user32.dll")] internal static extern bool EnumWindows(WindowCallback callback, IntPtr arg);
        [DllImport("user32.dll")] internal static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
        [DllImport("user32.dll", CharSet=CharSet.Unicode)] internal static extern int GetClassName(IntPtr window, StringBuilder name, int length);
        [DllImport("user32.dll", SetLastError=true)] internal static extern IntPtr SendMessageTimeout(IntPtr window, uint message, UIntPtr parameter, IntPtr value, uint flags, uint timeout, out UIntPtr result);
        [DllImport("wtsapi32.dll", SetLastError=true)] internal static extern bool WTSRegisterSessionNotification(IntPtr window, uint flags);
        [DllImport("wtsapi32.dll")] internal static extern bool WTSUnRegisterSessionNotification(IntPtr window);
    }

    internal sealed class Monitor {
        public Native.Rect bounds, work;
        public bool primary;
        public int scale;
        internal string Signature { get { return bounds + ":" + work + ":" + primary + ":" + scale; } }
    }
    internal sealed class Window {
        internal IntPtr handle;
        internal uint process;
        internal string name;
    }
    internal sealed class Snapshot {
        internal readonly List<Monitor> monitors = new List<Monitor>();
        internal readonly List<Window> receivers = new List<Window>();
        internal string signature;
        internal static HashSet<uint> WslProcesses(IEnumerable<Window> windows) {
            return new HashSet<uint>(windows.Where(w => w.name == "MSRDCSessionManager_WSL" || w.name == "MSRDCSysTrayClass_WSL").Select(w => w.process));
        }
        internal static string Signature(IEnumerable<Monitor> monitors, IEnumerable<Window> windows) {
            var processes = WslProcesses(windows);
            var geometry = monitors.Select(m => m.Signature).OrderBy(s => s, StringComparer.Ordinal);
            var connections = windows.Where(w => processes.Contains(w.process)).Select(w => w.process + ":" + w.handle.ToInt64()).OrderBy(s => s, StringComparer.Ordinal);
            return String.Join(";", geometry) + "|" + String.Join(";", connections);
        }
        internal static Snapshot Capture() {
            var snapshot = new Snapshot();
            if (!Native.EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, delegate(IntPtr h, IntPtr dc, IntPtr rect, IntPtr arg) {
                var info = new Native.MonitorInfo();
                info.size = Marshal.SizeOf(info);
                // A display can disappear between enumeration and this read.
                if (!Native.GetMonitorInfo(h, ref info)) return true;
                uint dpiX, dpiY;
                int scale = Native.GetDpiForMonitor(h, 0, out dpiX, out dpiY) == 0 ? (int)(dpiX * 100 / 96) : 0;
                snapshot.monitors.Add(new Monitor { bounds=info.monitor, work=info.work, primary=(info.flags & 1) != 0, scale=scale });
                return true;
            }, IntPtr.Zero) || snapshot.monitors.Count == 0) throw new InvalidOperationException("No monitor topology available");
            var windows = new List<Window>();
            Native.EnumWindows(delegate(IntPtr h, IntPtr arg) {
                var name = new StringBuilder(256);
                Native.GetClassName(h, name, name.Capacity);
                string cls = name.ToString();
                // These markers belong to the WSLg client, not ordinary RDP sessions.
                if (cls == "TsWindow_GeneralWindowClass" || cls == "RAIL_WINDOW" ||
                    cls == "MSRDCSessionManager_WSL" || cls == "MSRDCSysTrayClass_WSL") {
                    uint process;
                    Native.GetWindowThreadProcessId(h, out process);
                    windows.Add(new Window { handle=h, process=process, name=cls });
                }
                return true;
            }, IntPtr.Zero);
            var wslProcesses = WslProcesses(windows);
            snapshot.receivers.AddRange(windows.Where(w => w.name == "TsWindow_GeneralWindowClass" && wslProcesses.Contains(w.process)));
            // New RAIL windows also cover a new WSLg connection in an existing process.
            snapshot.signature = Signature(snapshot.monitors, windows);
            return snapshot;
        }
        internal int Refresh() {
            int delivered = 0;
            foreach (var receiver in receivers) {
                UIntPtr result;
                // Notify only WSLg's receiver. MSRDC re-reads every monitor's work area
                // and sends ClientSysparam over RAIL; no coordinates are supplied here.
                if (Native.SendMessageTimeout(receiver.handle, 0x001a, new UIntPtr(0x002f), IntPtr.Zero, 0x0022, 250, out result) != IntPtr.Zero) delivered++;
            }
            return delivered;
        }
    }

    internal sealed class Watcher : NativeWindow, IDisposable {
        private readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        private readonly EventWaitHandle stop;
        private readonly string statusPath;
        private string observed, reason = "startup";
        private DateTime due = DateTime.MinValue;
        private bool pending = true;
        private bool registered;
        private long refreshes;
        internal Watcher(string path) {
            statusPath = path;
            stop = new EventWaitHandle(false, EventResetMode.AutoReset, Program.StopName);
            CreateHandle(new CreateParams { Caption="WSLg work-area synchronization", Style=0 });
            registered = Native.WTSRegisterSessionNotification(Handle, 0);
            timer.Interval = 1000;
            timer.Tick += Tick;
            timer.Start();
            Tick(null, EventArgs.Empty);
        }
        private void Schedule(string why) {
            reason = why;
            due = DateTime.UtcNow.AddSeconds(2);
            pending = true;
        }
        private void Tick(object sender, EventArgs e) {
            if (stop.WaitOne(0)) { Application.ExitThread(); return; }
            try {
                // Retry registration if RDS services were not ready at logon.
                if (!registered) registered = Native.WTSRegisterSessionNotification(Handle, 0);
                Snapshot current = Snapshot.Capture();
                if (current.signature != observed) {
                    observed = current.signature;
                    Schedule("topology-workarea-or-wslg-connection");
                }
                if (pending && DateTime.UtcNow >= due && current.receivers.Count > 0) {
                    int delivered = current.Refresh();
                    if (delivered == current.receivers.Count) { pending = false; refreshes++; }
                    else due = DateTime.UtcNow.AddSeconds(3);
                    Program.Save(statusPath, new { version=1, running=true, process_id=Process.GetCurrentProcess().Id,
                        refreshed_at=DateTime.UtcNow.ToString("o"), reason=reason, refresh_count=refreshes,
                        receiver_count=current.receivers.Count, notifications_delivered=delivered,
                        session_notifications=registered, monitors=current.monitors, pending=pending,
                        source="Windows GetMonitorInfo; MSRDC RAIL ClientSysparam" });
                }
            } catch (Exception error) {
                Program.Save(statusPath, new { version=1, running=true, error=error.GetType().Name, message=error.Message });
                Schedule("retry-after-error");
            }
        }
        protected override void WndProc(ref Message message) {
            // These events can require a refresh even if the monitor dimensions stay the same.
            if (message.Msg == 0x007e || message.Msg == 0x001a || message.Msg == 0x02e0 ||
                message.Msg == 0x02b1 || message.Msg == 0x0218) Schedule("windows-message-0x" + message.Msg.ToString("x"));
            base.WndProc(ref message);
        }
        public void Dispose() {
            timer.Stop(); timer.Dispose();
            if (registered) Native.WTSUnRegisterSessionNotification(Handle);
            DestroyHandle(); stop.Dispose();
        }
    }

    internal static class Program {
        internal const string StopName = @"Local\wslg_remake.workarea-sync.stop.v1";
        private const string MutexName = @"Local\wslg_remake.workarea-sync.v1";
        internal static void Save(string path, object data) {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            string temporary = path + ".new";
            File.WriteAllText(temporary, new JavaScriptSerializer().Serialize(data), new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path);
        }
        [STAThread]
        private static int Main(string[] args) {
            string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "wslg_remake", "workarea-sync");
            string mode = args.Length > 0 ? args[0] : "--watch";
            string path = args.Length > 1 ? Path.GetFullPath(args[1]) : Path.Combine(folder, mode == "--watch" ? "status.json" : "last-refresh.json");
            if (mode == "--stop") {
                try { using (var handle = EventWaitHandle.OpenExisting(StopName)) handle.Set(); } catch (WaitHandleCannotBeOpenedException) { }
                return 0;
            }
            Native.SetProcessDpiAwarenessContext(new IntPtr(-4));
            Native.SetThreadDpiAwarenessContext(new IntPtr(-4));
            try {
                if (mode == "--once") {
                    var snapshot = Snapshot.Capture();
                    int delivered = snapshot.Refresh();
                    Save(path, new { version=1, refreshed_at=DateTime.UtcNow.ToString("o"), monitors=snapshot.monitors,
                        receiver_count=snapshot.receivers.Count, notifications_delivered=delivered });
                    return delivered > 0 && delivered == snapshot.receivers.Count ? 0 : 2;
                }
                if (mode != "--watch") return 64;
                bool created;
                using (var mutex = new Mutex(true, MutexName, out created)) {
                    if (!created) return 0;
                    using (var watcher = new Watcher(path)) Application.Run();
                }
                Save(path, new { version=1, running=false, stopped_at=DateTime.UtcNow.ToString("o") });
                return 0;
            } catch (Exception error) {
                Save(path, new { version=1, running=false, error=error.GetType().Name, message=error.Message });
                return 1;
            }
        }
    }
}
