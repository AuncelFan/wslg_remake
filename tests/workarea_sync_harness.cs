using System;
using System.Collections.Generic;
using WslgRemake;

internal static class WorkAreaSyncTests {
    private static int assertions;
    private static void Check(bool value, string message) {
        assertions++;
        if (!value) throw new Exception(message);
    }
    private static Monitor Display(int x, int y, int width, int height, int taskbar, bool primary, int scale) {
        return new Monitor { bounds=new Native.Rect { left=x, top=y, right=x+width, bottom=y+height },
            work=new Native.Rect { left=x, top=y, right=x+width, bottom=y+height-taskbar }, primary=primary, scale=scale };
    }
    public static int Main() {
        try {
            var windows = new List<Window> {
                new Window { handle=new IntPtr(11), process=1, name="MSRDCSessionManager_WSL" },
                new Window { handle=new IntPtr(12), process=1, name="TsWindow_GeneralWindowClass" }
            };
            // Synthetic monitor layouts; these are not copied from a live desktop.
            var current = new[] { Display(0,0,2560,1440,56,true,150), Display(2560,120,1440,900,40,false,100) };
            string baseline = Snapshot.Signature(current,windows);
            Check(baseline == Snapshot.Signature(new[] {current[1],current[0]},windows),"Enumeration order must not trigger refresh");
            var remoteSizes = new[] {new[] {1280,800,32},new[] {1920,1200,40},new[] {2880,1800,48},new[] {3440,1440,64}};
            foreach (var size in remoteSizes)
                Check(baseline != Snapshot.Signature(new[] { Display(0,0,size[0],size[1],size[2],true,150),current[1] },windows),"Remote geometry change was lost");
            Check(baseline != Snapshot.Signature(new[] {Display(0,0,2560,1440,72,true,150),current[1]},windows),"Taskbar height change was lost");
            var left = Display(0,0,2560,1440,0,true,150); left.work.left=64;
            Check(baseline != Snapshot.Signature(new[] {left,current[1]},windows),"Left taskbar was lost");
            var top = Display(0,0,2560,1440,0,true,150); top.work.top=64;
            Check(baseline != Snapshot.Signature(new[] {top,current[1]},windows),"Top taskbar was lost");
            var right = Display(0,0,2560,1440,0,true,150); right.work.right-=64;
            Check(baseline != Snapshot.Signature(new[] {right,current[1]},windows),"Right taskbar was lost");
            Check(baseline != Snapshot.Signature(new[] {current[0],Display(-1440,-160,1440,900,40,false,100)},windows),"Negative monitor origin was lost");
            Check(baseline != Snapshot.Signature(new[] {Display(0,0,2560,1440,56,false,150),Display(2560,120,1440,900,40,true,100)},windows),"Primary monitor switch was lost");
            Check(baseline != Snapshot.Signature(new[] {Display(0,0,2560,1440,56,true,200),current[1]},windows),"DPI change was lost");
            windows.Add(new Window {handle=new IntPtr(13),process=1,name="RAIL_WINDOW"});
            Check(baseline != Snapshot.Signature(current,windows),"New RAIL connection was lost");
            string withRail = Snapshot.Signature(current,windows);
            windows.Add(new Window {handle=new IntPtr(21),process=2,name="TsWindow_GeneralWindowClass"});
            Check(withRail == Snapshot.Signature(current,windows),"Ordinary RDP clients must be excluded");
            Check(!Snapshot.WslProcesses(windows).Contains(2),"Ordinary RDP receiver was selected");
            Console.WriteLine("PASS: " + assertions + " dynamic work-area checks");
            return 0;
        } catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; }
    }
}
