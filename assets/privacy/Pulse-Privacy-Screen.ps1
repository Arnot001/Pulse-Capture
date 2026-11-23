# Pulse Capture Privacy Screen v1.4.2 - pinned shortcuts no longer dismiss Full Cover.
# Windows PowerShell 5.1: powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File .\Pulse-Privacy-Screen-v1.4.2.ps1
# Fullscreen always has a native CLOSE button (plus Escape / Alt+F4); no hotkeys are required for exit.
# A safe FULL COVER test never changes the desktop icons or taskbar.
[CmdletBinding()]
param(
    [switch]$Watchdog,
    [switch]$Restore,
    [int]$ParentPid = 0
)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This prototype requires Windows.' }

$script:root = Join-Path $env:LOCALAPPDATA 'PulseCapturePrivacyScreen'
New-Item -ItemType Directory -Path $script:root -Force | Out-Null
$script:stateFile = Join-Path $script:root 'active-state.json'
$script:settingsFile = Join-Path $script:root 'settings.json'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

if (-not ('PulsePrivacy.Native' -as [type])) {
Add-Type -ReferencedAssemblies 'System.Windows.Forms.dll','System.Drawing.dll' -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace PulsePrivacy {
    public static class Native {
        public delegate bool EnumWindowsCallback(IntPtr hwnd, IntPtr lparam);
        [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string className, string title);
        [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string className, string title);
        [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetClassName(IntPtr hwnd, System.Text.StringBuilder text, int length);
        [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsCallback callback, IntPtr param);
        [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hwnd);
        [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
        [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd, int command);
        [DllImport("user32.dll", SetLastError=true)] private static extern IntPtr SetParent(IntPtr child, IntPtr newParent);
        [DllImport("user32.dll", SetLastError=true)] private static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int width, int height, uint flags);
        [DllImport("user32.dll", CharSet=CharSet.Auto)] private static extern IntPtr SendMessageTimeout(IntPtr hwnd, uint message, IntPtr wparam, IntPtr lparam, uint flags, uint timeout, out IntPtr result);
        [DllImport("user32.dll", EntryPoint="GetWindowLongPtr", SetLastError=true)] private static extern IntPtr GetWindowLong64(IntPtr hwnd, int index);
        [DllImport("user32.dll", EntryPoint="GetWindowLong", SetLastError=true)] private static extern int GetWindowLong32(IntPtr hwnd, int index);
        [DllImport("user32.dll", EntryPoint="SetWindowLongPtr", SetLastError=true)] private static extern IntPtr SetWindowLong64(IntPtr hwnd, int index, IntPtr value);
        [DllImport("user32.dll", EntryPoint="SetWindowLong", SetLastError=true)] private static extern int SetWindowLong32(IntPtr hwnd, int index, int value);
        [DllImport("user32.dll", SetLastError=true)] public static extern bool RegisterHotKey(IntPtr window, int id, uint modifiers, uint key);
        [DllImport("user32.dll")] public static extern bool UnregisterHotKey(IntPtr window, int id);
        [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Auto)]
        private struct SHFILEINFO {
            public IntPtr hIcon;
            public int iIcon;
            public uint dwAttributes;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst=260)] public string szDisplayName;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst=80)] public string szTypeName;
        }
        [DllImport("shell32.dll", CharSet=CharSet.Auto)]
        private static extern IntPtr SHGetFileInfo(string path, uint attributes, ref SHFILEINFO info, uint size, uint flags);
        [DllImport("user32.dll")] private static extern bool DestroyIcon(IntPtr icon);
        public static Icon GetShortcutIcon(string path) {
            SHFILEINFO info = new SHFILEINFO();
            try {
                if (SHGetFileInfo(path, 0, ref info, (uint)Marshal.SizeOf(typeof(SHFILEINFO)), 0x00000100) != IntPtr.Zero
                    && info.hIcon != IntPtr.Zero) {
                    try { return (Icon)Icon.FromHandle(info.hIcon).Clone(); }
                    finally { DestroyIcon(info.hIcon); }
                }
            } catch { /* icon lookup failure: use standard app icon */ }
            return null;
        }

        private static string ClassOf(IntPtr hwnd) {
            var buffer = new System.Text.StringBuilder(256);
            GetClassName(hwnd, buffer, buffer.Capacity);
            return buffer.ToString();
        }
        public static IntPtr FindIcons() {
            IntPtr progman = FindWindow("Progman", null);
            IntPtr view = progman == IntPtr.Zero ? IntPtr.Zero : FindWindowEx(progman, IntPtr.Zero, "SHELLDLL_DefView", null);
            if (view == IntPtr.Zero) {
                EnumWindows(delegate(IntPtr hwnd, IntPtr unused) {
                    IntPtr candidate = FindWindowEx(hwnd, IntPtr.Zero, "SHELLDLL_DefView", null);
                    if (candidate != IntPtr.Zero) { view = candidate; return false; }
                    return true;
                }, IntPtr.Zero);
            }
            return view == IntPtr.Zero ? IntPtr.Zero : FindWindowEx(view, IntPtr.Zero, "SysListView32", "FolderView");
        }
        public static IntPtr[] FindTaskbars() {
            var result = new List<IntPtr>();
            EnumWindows(delegate(IntPtr hwnd, IntPtr unused) {
                string name = ClassOf(hwnd);
                if (name == "Shell_TrayWnd" || name == "Shell_SecondaryTrayWnd") result.Add(hwnd);
                return true;
            }, IntPtr.Zero);
            return result.ToArray();
        }
        public static IntPtr FindWallpaperWorker() {
            IntPtr progman = FindWindow("Progman", null);
            if (progman != IntPtr.Zero) {
                IntPtr result;
                // Ask Explorer to create a WorkerW desktop layer if supported.
                SendMessageTimeout(progman, 0x052C, IntPtr.Zero, IntPtr.Zero, 0, 1000, out result);
            }
            IntPtr worker = IntPtr.Zero;
            EnumWindows(delegate(IntPtr hwnd, IntPtr unused) {
                if (FindWindowEx(hwnd, IntPtr.Zero, "SHELLDLL_DefView", null) != IntPtr.Zero) {
                    worker = FindWindowEx(IntPtr.Zero, hwnd, "WorkerW", null);
                    if (worker != IntPtr.Zero) return false;
                }
                return true;
            }, IntPtr.Zero);
            return worker;
        }
        private static long GetStyle(IntPtr hwnd) {
            return IntPtr.Size == 8 ? GetWindowLong64(hwnd, -16).ToInt64() : (uint)GetWindowLong32(hwnd, -16);
        }
        private static void SetStyle(IntPtr hwnd, long style) {
            if (IntPtr.Size == 8) SetWindowLong64(hwnd, -16, new IntPtr(style));
            else SetWindowLong32(hwnd, -16, unchecked((int)style));
        }
        public static bool AttachToWorker(IntPtr window, IntPtr worker, Rectangle bounds) {
            if (worker == IntPtr.Zero || !IsWindow(worker)) return false;
            long style = GetStyle(window);
            SetStyle(window, (style | 0x40000000L) & ~0x80000000L); // WS_CHILD, not WS_POPUP
            SetParent(window, worker);
            return SetWindowPos(window, IntPtr.Zero, bounds.X, bounds.Y, bounds.Width, bounds.Height,
                0x0004 | 0x0010 | 0x0020); // NOZORDER | NOACTIVATE | FRAMECHANGED
        }
        public static void SendBehind(IntPtr window) {
            SetWindowPos(window, new IntPtr(1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010); // BOTTOM, NOMOVE, NOSIZE, NOACTIVATE
        }
    }

    public class Canvas : Form {
        public Image SelectedImage { get; set; }
        public string FitMode { get; set; }
        public string ThemeMode { get; set; }
        public bool Passive { get; set; }
        protected override bool ShowWithoutActivation { get { return Passive; } }
        public Canvas() {
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            DoubleBuffered = true;
            KeyPreview = true;
            BackColor = Color.Black;
            FitMode = "Fill";
            ThemeMode = "Black";
        }
        protected override void OnPaint(PaintEventArgs e) {
            base.OnPaint(e);
            Graphics g = e.Graphics;
            g.Clear(Color.Black);
            if (SelectedImage != null && ThemeMode == "Custom image") {
                double iw = SelectedImage.Width, ih = SelectedImage.Height;
                double sx = ClientSize.Width / iw, sy = ClientSize.Height / ih;
                double factor = FitMode == "Fit" ? Math.Min(sx,sy) : FitMode == "Center" ? 1.0 : Math.Max(sx,sy);
                int w = Math.Max(1,(int)Math.Round(iw*factor)), h = Math.Max(1,(int)Math.Round(ih*factor));
                int x = (ClientSize.Width-w)/2, y = (ClientSize.Height-h)/2;
                g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                g.DrawImage(SelectedImage, new Rectangle(x,y,w,h));
            } else if (ThemeMode == "Pulse dark") {
                using(var brush = new LinearGradientBrush(ClientRectangle, Color.FromArgb(7,13,28), Color.FromArgb(22,42,70), 20f)) g.FillRectangle(brush, ClientRectangle);
                using(var font = new Font("Segoe UI", 37, FontStyle.Bold, GraphicsUnit.Pixel))
                using(var textBrush = new SolidBrush(Color.FromArgb(175,205,230))) {
                    var text = "PULSE CAPTURE";
                    var size = g.MeasureString(text,font);
                    g.DrawString(text,font,textBrush,(ClientSize.Width-size.Width)/2,(ClientSize.Height-size.Height)/2);
                }
            }
        }
    }
    // Native clickable tile: click to launch; drag to reposition. No real desktop
    // shortcuts are modified or exposed by the privacy layer.
    public sealed class ShortcutTile : Control {
        public readonly int Slot;
        public readonly string TargetPath;
        private readonly Icon icon;
        private bool hover;
        private bool pointerDown;
        private bool moved;
        private Point downAtScreen;
        private Point originalLocation;
        public event EventHandler Launched;
        public event EventHandler PositionCommitted;

        public ShortcutTile(int slot, string path, Point location) {
            Slot = slot;
            TargetPath = path;
            Text = Path.GetFileNameWithoutExtension(path);
            Location = location;
            Size = new Size(122, 104);
            TabStop = true;
            Cursor = Cursors.Hand;
            Font = new Font("Segoe UI", 10, FontStyle.Regular);
            // WinForms rejects Color.Transparent unless transparency support is
            // enabled FIRST. This ordering fixes pinned tiles failing to show.
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.SupportsTransparentBackColor |
                     ControlStyles.Selectable, true);
            BackColor = Color.Transparent;
            icon = Native.GetShortcutIcon(path);
            AccessibleName = "Launch " + Text;
            AccessibleDescription = "Click to open, or drag to move this pinned shortcut";
        }
        protected override void OnPaint(PaintEventArgs e) {
            base.OnPaint(e);
            var r = new Rectangle(2,2,Width-5,Height-5);
            using (var b = new SolidBrush(Color.FromArgb(hover || Focused ? 205 : 145, 12, 23, 37)))
                e.Graphics.FillRectangle(b, r);
            using (var p = new Pen(Color.FromArgb(hover || Focused ? 165 : 75, 160, 188, 210)))
                e.Graphics.DrawRectangle(p, r);
            if (icon != null) e.Graphics.DrawIcon(icon, new Rectangle((Width-40)/2, 9, 40, 40));
            else e.Graphics.DrawIcon(SystemIcons.Application, new Rectangle((Width-40)/2, 9, 40, 40));
            TextRenderer.DrawText(e.Graphics, Text, Font, new Rectangle(6, 56, Width-12, 43),
                Color.FromArgb(242,247,252), TextFormatFlags.HorizontalCenter |
                TextFormatFlags.WordBreak | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
        }
        protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); hover = true; Invalidate(); }
        protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); hover = false; Invalidate(); }
        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
        protected override void OnMouseDown(MouseEventArgs e) {
            base.OnMouseDown(e);
            if (e.Button != MouseButtons.Left) return;
            Focus();
            pointerDown = true;
            moved = false;
            downAtScreen = Cursor.Position;
            originalLocation = Location;
            Capture = true;
        }
        protected override void OnMouseMove(MouseEventArgs e) {
            base.OnMouseMove(e);
            if (!pointerDown) return;
            int dx = Cursor.Position.X - downAtScreen.X;
            int dy = Cursor.Position.Y - downAtScreen.Y;
            if (!moved && Math.Abs(dx) < 7 && Math.Abs(dy) < 7) return;
            moved = true;
            int x = Math.Max(5, Math.Min(Math.Max(5, Parent.ClientSize.Width - Width - 5), originalLocation.X + dx));
            int y = Math.Max(65, Math.Min(Math.Max(65, Parent.ClientSize.Height - Height - 5), originalLocation.Y + dy));
            Location = new Point(x,y);
        }
        protected override void OnMouseUp(MouseEventArgs e) {
            base.OnMouseUp(e);
            if (e.Button != MouseButtons.Left || !pointerDown) return;
            pointerDown = false;
            Capture = false;
            if (moved) {
                if (PositionCommitted != null) PositionCommitted(this, EventArgs.Empty);
            } else Launch();
        }
        protected override void OnKeyDown(KeyEventArgs e) {
            if (e.KeyCode == Keys.Enter || e.KeyCode == Keys.Space) {
                e.Handled = true;
                Launch();
            } else base.OnKeyDown(e);
        }
        private void Launch() {
            try {
                if (!File.Exists(TargetPath)) throw new FileNotFoundException("Shortcut no longer exists", TargetPath);
                string ext = Path.GetExtension(TargetPath).ToLowerInvariant();
                if (ext != ".lnk" && ext != ".url" && ext != ".exe")
                    throw new InvalidOperationException("Only Windows shortcuts and applications can be pinned.");
                Process.Start(new ProcessStartInfo(TargetPath) { UseShellExecute = true });
                if (Launched != null) Launched(this, EventArgs.Empty);
            } catch (Exception ex) {
                MessageBox.Show("Cannot open this shortcut: " + ex.Message, "Pulse Privacy", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }
        protected override void Dispose(bool disposing) {
            if (disposing && icon != null) icon.Dispose();
            base.Dispose(disposing);
        }
    }

    // Keep the escape route entirely in managed Windows Forms code. This does NOT
    // depend on a PowerShell event scriptblock running successfully.
    public sealed class FullCover : Canvas {
        private readonly Button closeButton;
        private readonly ToolTip closeTip;
        private readonly List<ShortcutTile> pinnedTiles = new List<ShortcutTile>();
        public event EventHandler Dismissed;
        public event EventHandler ShortcutPositionsChanged;
        private bool inDismiss;

        public FullCover() : base() {
            ShowInTaskbar = true; // Alt+Tab can bring up another application as a fallback.
            TopMost = false;      // Do not trap Task Manager or other apps behind us.
            Text = "Pulse Privacy Cover - Esc / Alt+F4 to close";
            closeButton = new Button();
            closeButton.Name = "ClosePrivacyCover";
            // Compact, always-visible exit that doesn't dominate the artwork.
            // The tooltip explains the shortcuts without putting them on screen.
            closeButton.Text = "\u00D7";
            closeButton.Size = new Size(46, 44);
            closeButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            closeButton.Font = new Font("Segoe UI", 18, FontStyle.Regular);
            closeButton.ForeColor = Color.FromArgb(210, 222, 235);
            closeButton.BackColor = Color.FromArgb(24, 36, 53);
            closeButton.FlatStyle = FlatStyle.Flat;
            closeButton.FlatAppearance.BorderColor = Color.FromArgb(78, 99, 124);
            closeButton.FlatAppearance.BorderSize = 1;
            closeButton.FlatAppearance.MouseOverBackColor = Color.FromArgb(91, 48, 58);
            closeButton.FlatAppearance.MouseDownBackColor = Color.FromArgb(117, 52, 66);
            closeButton.AccessibleName = "Close privacy screen";
            closeButton.AccessibleDescription = "Dismiss fullscreen (Escape or Alt+F4 also work)";
            closeButton.TabStop = true;
            closeButton.Click += delegate(object sender, EventArgs e) { Dismiss(); };
            Controls.Add(closeButton);
            closeTip = new ToolTip();
            closeTip.InitialDelay = 350;
            closeTip.AutoPopDelay = 5000;
            closeTip.SetToolTip(closeButton, "Close privacy screen (Esc / Alt+F4)");
            CancelButton = closeButton; // The Esc key works when the button owns focus.
            PositionClose();
        }
        public void SetShortcuts(string first, string second, int x1, int y1, int x2, int y2) {
            foreach (ShortcutTile tile in pinnedTiles) { Controls.Remove(tile); tile.Dispose(); }
            pinnedTiles.Clear();
            AddTile(1, first, new Point(x1,y1));
            AddTile(2, second, new Point(x2,y2));
            closeButton.BringToFront();
        }
        private void AddTile(int slot, string path, Point location) {
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) return;
            string ext = Path.GetExtension(path).ToLowerInvariant();
            if (ext != ".lnk" && ext != ".url" && ext != ".exe") return;
            Point safeLocation = new Point(
                Math.Max(5, Math.Min(Math.Max(5, ClientSize.Width - 127), location.X)),
                Math.Max(65, Math.Min(Math.Max(65, ClientSize.Height - 109), location.Y)));
            ShortcutTile tile = new ShortcutTile(slot, path, safeLocation);
            // Do NOT dismiss the privacy screen when an app is launched.
            // FullCover is intentionally not TopMost, so the opened application
            // can appear in front while this remains available behind it.
            // The close button, Esc and Alt+F4 still dismiss the cover.
            tile.PositionCommitted += delegate(object sender, EventArgs e) {
                if (ShortcutPositionsChanged != null) ShortcutPositionsChanged(this, EventArgs.Empty);
            };
            pinnedTiles.Add(tile);
            Controls.Add(tile);
            tile.BringToFront();
        }
        public Point GetShortcutPosition(int slot) {
            foreach (ShortcutTile tile in pinnedTiles)
                if (tile.Slot == slot) return tile.Location;
            return Point.Empty;
        }
        private void PositionClose() {
            if (closeButton != null) closeButton.Location =
                new Point(Math.Max(4, ClientSize.Width - closeButton.Width - 16), 14);
        }
        protected override void OnResize(EventArgs e) {
            base.OnResize(e);
            PositionClose();
        }
        protected override void OnShown(EventArgs e) {
            base.OnShown(e);
            // Allow the native close button to be clicked immediately.
            // Escape and Alt+F4 are handled independently by ProcessCmdKey.
        }
        public void Dismiss() {
            if (inDismiss) return;
            inDismiss = true;
            try { Hide(); } finally { inDismiss = false; }
            if (Dismissed != null) Dismissed(this, EventArgs.Empty);
        }
        protected override bool ProcessCmdKey(ref Message msg, Keys keyData) {
            if (keyData == Keys.Escape || keyData == (Keys.Alt | Keys.F4)) {
                Dismiss();
                return true;
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }
        protected override void OnFormClosing(FormClosingEventArgs e) {
            if (e.CloseReason == CloseReason.UserClosing) {
                e.Cancel = true;
                Dismiss();
                return;
            }
            base.OnFormClosing(e);
        }
    }
    public sealed class Controls : Form {
        public event EventHandler RestorePressed;
        public event EventHandler ShowControlsPressed;
        protected override void WndProc(ref Message m) {
            if (m.Msg == 0x0312) {
                if (m.WParam.ToInt32() == 1) { if (RestorePressed != null) RestorePressed(this,EventArgs.Empty); return; }
                if (m.WParam.ToInt32() == 2) { if (ShowControlsPressed != null) ShowControlsPressed(this,EventArgs.Empty); return; }
            }
            base.WndProc(ref m);
        }
    }
}
'@
}

function Get-CurrentState {
    $icon = [PulsePrivacy.Native]::FindIcons()
    $bars = @()
    foreach ($b in [PulsePrivacy.Native]::FindTaskbars()) {
        $bars += [pscustomobject]@{ Handle = $b.ToInt64(); WasVisible = [bool][PulsePrivacy.Native]::IsWindowVisible($b) }
    }
    [pscustomobject]@{
        OwnerPid = $PID
        IconHandle = $icon.ToInt64()
        IconVisible = if ($icon -ne [IntPtr]::Zero) { [bool][PulsePrivacy.Native]::IsWindowVisible($icon) } else { $false }
        # Restore only settings this app actually changes, not all shell visibility.
        RestoreIcons = [bool]$script:checkIcons.Checked
        RestoreTaskbar = [bool]$script:checkBar.Checked
        Taskbars = $bars
        StartedUtc = [DateTime]::UtcNow.ToString('o')
    }
}

function Restore-DesktopState($saved) {
    if ($null -eq $saved) { return }
    # Treat old v1.1 state files as restorable (they did not have the flags).
    $restoreIcons = ($null -eq $saved.RestoreIcons) -or [bool]$saved.RestoreIcons
    $restoreTaskbar = ($null -eq $saved.RestoreTaskbar) -or [bool]$saved.RestoreTaskbar
    if ($restoreIcons) {
        $icon = [IntPtr][long]$saved.IconHandle
        if ($icon -eq [IntPtr]::Zero -or -not [PulsePrivacy.Native]::IsWindow($icon)) { $icon = [PulsePrivacy.Native]::FindIcons() }
        if ($icon -ne [IntPtr]::Zero) {
            $command = if ([bool]$saved.IconVisible) { 5 } else { 0 }
            [void][PulsePrivacy.Native]::ShowWindow($icon, $command)
        }
    }
    if ($restoreTaskbar) {
        $currentBars = @([PulsePrivacy.Native]::FindTaskbars())
        foreach ($bar in @($saved.Taskbars)) {
            $hwnd = [IntPtr][long]$bar.Handle
            if (-not [PulsePrivacy.Native]::IsWindow($hwnd)) {
                if ($currentBars.Count -gt 0) { $hwnd = $currentBars[0]; $currentBars = @($currentBars | Select-Object -Skip 1) }
            }
            if ($hwnd -ne [IntPtr]::Zero -and [PulsePrivacy.Native]::IsWindow($hwnd)) {
                $command = if ([bool]$bar.WasVisible) { 5 } else { 0 }
                [void][PulsePrivacy.Native]::ShowWindow($hwnd, $command)
            }
        }
    }
}

function Recover-FromFile {
    if (-not (Test-Path -LiteralPath $script:stateFile)) { return }
    try {
        $saved = Get-Content -LiteralPath $script:stateFile -Raw | ConvertFrom-Json
        Restore-DesktopState $saved
    } finally {
        Remove-Item -LiteralPath $script:stateFile -Force -ErrorAction SilentlyContinue
    }
}

# Emergency command-line recovery without opening the UI.
if ($Restore) {
    try { Recover-FromFile; Write-Host "Pulse privacy desktop settings restored." }
    catch { Write-Error $_; exit 1 }
    exit 0
}

# Watchdog child runs without the GUI. When the main process disappears, restore the desktop.
if ($Watchdog) {
    while (Test-Path -LiteralPath $script:stateFile) {
        $alive = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
        if (-not $alive) {
            try { Recover-FromFile } catch { }
            break
        }
        Start-Sleep -Milliseconds 700
    }
    exit 0
}

# If a previous run crashed, recover before starting another session.
if (Test-Path -LiteralPath $script:stateFile) {
    try {
        $old = Get-Content -LiteralPath $script:stateFile -Raw | ConvertFrom-Json
        if (Get-Process -Id ([int]$old.OwnerPid) -ErrorAction SilentlyContinue) {
            [System.Windows.Forms.MessageBox]::Show('Pulse Privacy is already running. Use Ctrl+Alt+Shift+C to open its controls.', 'Pulse Privacy') | Out-Null
            exit 0
        }
        Recover-FromFile
    } catch {
        [System.Windows.Forms.MessageBox]::Show('Could not safely recover a previous privacy session. Restart Explorer if the taskbar or desktop icons are missing.', 'Pulse Privacy') | Out-Null
        exit 1
    }
}

$script:isActive = $false
$script:coverActive = $false
$script:imageBitmap = $null
$script:savedState = $null
$script:workerMode = $false
$script:hotkeys = @()
$script:restoreHotkeyName = ''
$script:showHotkeyName = ''

$script:panel = [PulsePrivacy.Controls]::new()
$script:panel.Text = 'Pulse Capture | Privacy Screen'
$script:panel.Size = [System.Drawing.Size]::new(495,652)
$script:panel.StartPosition = 'CenterScreen'
$script:panel.FormBorderStyle = 'FixedDialog'
$script:panel.MaximizeBox = $false
$script:panel.BackColor = [System.Drawing.Color]::FromArgb(16,22,32)
$script:panel.ForeColor = [System.Drawing.Color]::White
$script:panel.Font = [System.Drawing.Font]::new('Segoe UI', 10)

function Add-Label([string]$text, [int]$x, [int]$y, [int]$width, [int]$height=24) {
    $label = [System.Windows.Forms.Label]::new()
    $label.Text = $text
    $label.Location = [System.Drawing.Point]::new($x,$y)
    $label.Size = [System.Drawing.Size]::new($width,$height)
    $script:panel.Controls.Add($label)
    return $label
}
function Add-Button([string]$text,[int]$x,[int]$y,[int]$w,[int]$h) {
    $button = [System.Windows.Forms.Button]::new()
    $button.Text = $text
    $button.Location = [System.Drawing.Point]::new($x,$y)
    $button.Size = [System.Drawing.Size]::new($w,$h)
    $button.FlatStyle = 'Flat'
    $button.BackColor = [System.Drawing.Color]::FromArgb(39,60,84)
    $button.ForeColor = [System.Drawing.Color]::White
    $script:panel.Controls.Add($button)
    return $button
}

$title = Add-Label 'PRIVACY SCREEN' 20 20 420 34
$title.Font = [System.Drawing.Font]::new('Segoe UI',18,[System.Drawing.FontStyle]::Bold)
$info = Add-Label 'First test FULL COVER safely. Icons/taskbar start untouched.' 20 58 450 34
$info.ForeColor = [System.Drawing.Color]::FromArgb(188,204,219)

$script:checkIcons = [System.Windows.Forms.CheckBox]::new()
$script:checkIcons.Text = 'Hide desktop icons'
$script:checkIcons.Checked = $false
$script:checkIcons.SetBounds(24,101,200,30)
$script:panel.Controls.Add($script:checkIcons)
$script:checkBar = [System.Windows.Forms.CheckBox]::new()
$script:checkBar.Text = 'Hide taskbar (including secondary monitors)'
$script:checkBar.Checked = $false
$script:checkBar.SetBounds(24,133,410,30)
$script:panel.Controls.Add($script:checkBar)

[void](Add-Label 'Background' 22 178 110)
$script:backgroundChoice = [System.Windows.Forms.ComboBox]::new()
$script:backgroundChoice.DropDownStyle = 'DropDownList'
$script:backgroundChoice.SetBounds(140,176,315,30)
[void]$script:backgroundChoice.Items.AddRange([object[]]@('Black','Pulse dark','Custom image'))
$script:backgroundChoice.SelectedIndex = 1
$script:panel.Controls.Add($script:backgroundChoice)

[void](Add-Label 'Image fit' 22 219 110)
$script:fitChoice = [System.Windows.Forms.ComboBox]::new()
$script:fitChoice.DropDownStyle = 'DropDownList'
$script:fitChoice.SetBounds(140,217,130,30)
[void]$script:fitChoice.Items.AddRange([object[]]@('Fill','Fit','Center'))
$script:fitChoice.SelectedIndex = 0
$script:panel.Controls.Add($script:fitChoice)

$script:chooseButton = Add-Button 'Choose image...' 289 215 166 32
$script:imagePathLabel = Add-Label 'No image selected' 22 258 442 40
$script:imagePathLabel.ForeColor = [System.Drawing.Color]::FromArgb(180,198,210)

[void](Add-Label 'PINNED SHORTCUTS (launch apps over cover / drag to move)' 22 296 453 25)
$script:shortcut1Label = Add-Label '1. (none)' 24 328 260 29
$script:pickShortcut1 = Add-Button 'Choose...' 302 327 83 29
$script:clearShortcut1 = Add-Button 'Clear' 393 327 64 29
$script:shortcut2Label = Add-Label '2. (none)' 24 366 260 29
$script:pickShortcut2 = Add-Button 'Choose...' 302 365 83 29
$script:clearShortcut2 = Add-Button 'Clear' 393 365 64 29
$script:shortcutTip = [System.Windows.Forms.ToolTip]::new()

$script:activateButton = Add-Button 'ACTIVATE' 20 416 136 42
$script:restoreButton = Add-Button 'RESTORE DESKTOP' 165 416 150 42
$script:coverButton = Add-Button 'TEST FULL COVER' 325 416 140 42
$script:hideButton = Add-Button 'Hide controls' 20 470 160 35
$script:statusLabel = Add-Label 'OFF - desktop unchanged' 195 478 275 28
$script:statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(160,220,174)
$script:restoreHotkeyLabel = Add-Label 'Emergency restore: registering shortcut...' 20 517 455 25
$script:showHotkeyLabel = Add-Label 'Show controls: registering shortcut...' 20 541 460 22

$script:backgroundForm = [PulsePrivacy.Canvas]::new()
$script:backgroundForm.Passive = $true
$script:backgroundForm.Bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$script:coverForm = [PulsePrivacy.FullCover]::new()
$script:coverForm.Bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$script:coverForm.TopMost = $false

$script:settings = [pscustomobject]@{
    ImagePath = ''; Background = 'Pulse dark'; Fit = 'Fill'; HideIcons = $false; HideTaskbar = $false
    Shortcut1Path = ''; Shortcut2Path = ''
    Shortcut1X = 32; Shortcut1Y = 86; Shortcut2X = 32; Shortcut2Y = 200
}
if (Test-Path -LiteralPath $script:settingsFile) {
    try {
        $savedSettings = Get-Content -LiteralPath $script:settingsFile -Raw | ConvertFrom-Json
        if ($null -ne $savedSettings.ImagePath) { $script:settings.ImagePath = [string]$savedSettings.ImagePath }
        if ([string]$savedSettings.Background -in @('Black','Pulse dark','Custom image')) { $script:settings.Background = [string]$savedSettings.Background }
        if ([string]$savedSettings.Fit -in @('Fill','Fit','Center')) { $script:settings.Fit = [string]$savedSettings.Fit }
        foreach ($slot in 1..2) {
            $name = 'Shortcut' + $slot + 'Path'
            $value = [string]$savedSettings.$name
            if ($value -and [System.IO.Path]::GetExtension($value).ToLowerInvariant() -in @('.lnk','.url','.exe') -and
                (Test-Path -LiteralPath $value -PathType Leaf)) {
                $script:settings.$name = $value
            }
            foreach ($axis in @('X','Y')) {
                $coordName = 'Shortcut' + $slot + $axis
                $coord = 0
                if ([int]::TryParse([string]$savedSettings.$coordName, [ref]$coord) -and $coord -ge 0 -and $coord -le 16384) {
                    $script:settings.$coordName = $coord
                }
            }
        }
        # Intentionally do NOT restore last run's hide flags. After the stuck
        # fullscreen incident, these must be explicitly opted into each launch.
        $script:settings.HideIcons = $false
        $script:settings.HideTaskbar = $false
    } catch { }
}
$script:checkIcons.Checked = $script:settings.HideIcons
$script:checkBar.Checked = $script:settings.HideTaskbar
$script:backgroundChoice.SelectedItem = $script:settings.Background
$script:fitChoice.SelectedItem = $script:settings.Fit
if ($script:settings.ImagePath) { $script:imagePathLabel.Text = $script:settings.ImagePath }
function Update-ShortcutLabels {
    foreach ($slot in 1..2) {
        $name = 'Shortcut' + $slot + 'Path'
        $label = if ($slot -eq 1) { $script:shortcut1Label } else { $script:shortcut2Label }
        $path = [string]$script:settings.$name
        $display = if ($path) { [System.IO.Path]::GetFileNameWithoutExtension($path) } else { '(none)' }
        if ($display.Length -gt 27) { $display = $display.Substring(0,24) + '...' }
        $label.Text = "$slot. $display"
        $script:shortcutTip.SetToolTip($label, $path)
    }
}
function Set-PinnedShortcuts {
    $script:coverForm.SetShortcuts(
        [string]$script:settings.Shortcut1Path, [string]$script:settings.Shortcut2Path,
        [int]$script:settings.Shortcut1X, [int]$script:settings.Shortcut1Y,
        [int]$script:settings.Shortcut2X, [int]$script:settings.Shortcut2Y
    )
}
function Save-ShortcutPositions {
    foreach ($slot in 1..2) {
        $point = $script:coverForm.GetShortcutPosition([int]$slot)
        if (-not $point.IsEmpty) {
            if ($slot -eq 1) {
                $script:settings.Shortcut1X = [int]$point.X
                $script:settings.Shortcut1Y = [int]$point.Y
            } else {
                $script:settings.Shortcut2X = [int]$point.X
                $script:settings.Shortcut2Y = [int]$point.Y
            }
        }
    }
    Save-Settings
}
Update-ShortcutLabels

function Set-Theme {
    $choice = [string]$script:backgroundChoice.SelectedItem
    $fit = [string]$script:fitChoice.SelectedItem
    if ($choice -eq 'Custom image') {
        if (-not $script:settings.ImagePath -or -not (Test-Path -LiteralPath $script:settings.ImagePath -PathType Leaf)) {
            throw 'Choose an existing PNG or JPG image first.'
        }
        $loaded = [System.Drawing.Image]::FromFile($script:settings.ImagePath)
        try { $bitmap = [System.Drawing.Bitmap]::new($loaded) } finally { $loaded.Dispose() }
        $script:backgroundForm.SelectedImage = $bitmap
        $script:coverForm.SelectedImage = $bitmap
        if ($null -ne $script:imageBitmap) { $script:imageBitmap.Dispose() }
        $script:imageBitmap = $bitmap
    } else {
        $script:backgroundForm.SelectedImage = $null
        $script:coverForm.SelectedImage = $null
        if ($null -ne $script:imageBitmap) { $script:imageBitmap.Dispose(); $script:imageBitmap = $null }
    }
    foreach ($form in @($script:backgroundForm, $script:coverForm)) {
        $form.ThemeMode = $choice
        $form.FitMode = $fit
        $form.Invalidate()
    }
}
function Save-Settings {
    $script:settings.Background = [string]$script:backgroundChoice.SelectedItem
    $script:settings.Fit = [string]$script:fitChoice.SelectedItem
    $script:settings.HideIcons = [bool]$script:checkIcons.Checked
    $script:settings.HideTaskbar = [bool]$script:checkBar.Checked
    $script:settings | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $script:settingsFile -Encoding UTF8
}
function End-FullCover {
    if ($script:coverForm.Visible) { $script:coverForm.Dismiss() }
    $script:coverActive = $false
    $script:coverButton.Text = if ($script:isActive) { 'FULL COVER' } else { 'TEST FULL COVER' }
}
function Restore-Privacy {
    End-FullCover
    try {
        if ($script:backgroundForm.Visible) { $script:backgroundForm.Hide() }
        if ($script:savedState) { Restore-DesktopState $script:savedState }
        elseif (Test-Path -LiteralPath $script:stateFile) { Recover-FromFile }
    } finally {
        # The watchdog exits as soon as this file disappears.
        Remove-Item -LiteralPath $script:stateFile -Force -ErrorAction SilentlyContinue
        $script:savedState = $null
        $script:isActive = $false
        $script:coverButton.Text = 'TEST FULL COVER'
        $script:statusLabel.Text = 'OFF - desktop restored'
        $script:statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(160,220,174)
    }
}
function Activate-Privacy {
    if ($script:isActive) { return }
    Set-Theme
    Save-Settings
    $script:savedState = Get-CurrentState
    # Persist the original state before modifying Explorer.
    $script:savedState | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $script:stateFile -Encoding UTF8
    try {
        $powershellExe = (Get-Process -Id $PID).Path
        if (-not $powershellExe) { $powershellExe = Join-Path $PSHOME 'powershell.exe' }
        $watchArgs = @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',('"' + $PSCommandPath + '"'),'-Watchdog','-ParentPid',"$PID")
        Start-Process -FilePath $powershellExe -ArgumentList $watchArgs -WindowStyle Hidden | Out-Null

        $script:backgroundForm.Bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $script:backgroundForm.Show()
        $worker = [PulsePrivacy.Native]::FindWallpaperWorker()
        if ($worker -ne [IntPtr]::Zero) {
            $script:workerMode = [PulsePrivacy.Native]::AttachToWorker($script:backgroundForm.Handle, $worker, [System.Windows.Forms.Screen]::PrimaryScreen.Bounds)
        }
        if (-not $script:workerMode) { $script:backgroundForm.SendToBack(); [PulsePrivacy.Native]::SendBehind($script:backgroundForm.Handle) }

        if ($script:checkIcons.Checked -and [long]$script:savedState.IconHandle -ne 0) {
            [void][PulsePrivacy.Native]::ShowWindow([IntPtr][long]$script:savedState.IconHandle,0)
        }
        if ($script:checkBar.Checked) {
            foreach ($bar in @($script:savedState.Taskbars)) {
                [void][PulsePrivacy.Native]::ShowWindow([IntPtr][long]$bar.Handle,0)
            }
        }
        $script:isActive = $true
        $script:coverButton.Text = 'FULL COVER'
        $script:statusLabel.Text = 'ON - privacy background active'
        $script:statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(130,226,166)
        $script:panel.Activate()
    } catch {
        Restore-Privacy
        throw
    }
}

function Choose-PinnedShortcut([int]$slot) {
    $dialog = [System.Windows.Forms.OpenFileDialog]::new()
    $dialog.Title = 'Choose a Windows desktop shortcut or application'
    $dialog.Filter = 'Shortcuts and apps (*.lnk;*.url;*.exe)|*.lnk;*.url;*.exe'
    $dialog.DereferenceLinks = $false # Preserve shortcut arguments and working directory.
    $dialog.InitialDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
    try {
        if ($dialog.ShowDialog($script:panel) -eq [System.Windows.Forms.DialogResult]::OK) {
            if ($slot -eq 1) { $script:settings.Shortcut1Path = $dialog.FileName }
            else { $script:settings.Shortcut2Path = $dialog.FileName }
            Update-ShortcutLabels
            Set-PinnedShortcuts
            Save-Settings
        }
    } finally { $dialog.Dispose() }
}
$script:pickShortcut1.Add_Click({ Choose-PinnedShortcut 1 })
$script:pickShortcut2.Add_Click({ Choose-PinnedShortcut 2 })
$script:clearShortcut1.Add_Click({ $script:settings.Shortcut1Path = ''; Update-ShortcutLabels; Set-PinnedShortcuts; Save-Settings })
$script:clearShortcut2.Add_Click({ $script:settings.Shortcut2Path = ''; Update-ShortcutLabels; Set-PinnedShortcuts; Save-Settings })
$script:coverForm.Add_ShortcutPositionsChanged({ Save-ShortcutPositions })
$script:chooseButton.Add_Click({
    $dialog = [System.Windows.Forms.OpenFileDialog]::new()
    $dialog.Title = 'Choose your privacy image'
    $dialog.Filter = 'Images (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg|All files (*.*)|*.*'
    if ($dialog.ShowDialog($script:panel) -eq [System.Windows.Forms.DialogResult]::OK) {
        $script:settings.ImagePath = $dialog.FileName
        $script:imagePathLabel.Text = $dialog.FileName
        $script:backgroundChoice.SelectedItem = 'Custom image'
        try { Set-Theme; Save-Settings } catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message,'Image problem') | Out-Null }
    }
    $dialog.Dispose()
})
$script:backgroundChoice.Add_SelectedIndexChanged({
    if ($script:isActive) { try { Set-Theme; Save-Settings } catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message,'Image problem') | Out-Null } }
})
$script:fitChoice.Add_SelectedIndexChanged({
    if ($script:isActive) { try { Set-Theme; Save-Settings } catch { } }
})
$script:activateButton.Add_Click({
    try { Activate-Privacy }
    catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message,'Cannot activate privacy') | Out-Null }
})
$script:restoreButton.Add_Click({ Restore-Privacy })
$script:coverButton.Add_Click({
    # Critical safety rule: testing FULL COVER never activates background mode,
    # hides icons, or touches the taskbar. Test the native CLOSE button first.
    if ($script:coverForm.Visible) { End-FullCover; return }
    try {
        Set-Theme
        Save-Settings
        $script:coverForm.Bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        Set-PinnedShortcuts
        $script:coverForm.Show()
        $script:coverForm.BringToFront()
        $script:coverForm.Activate()
        $script:coverActive = $true
        $script:coverButton.Text = 'EXIT COVER'
    } catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Cannot show full cover') | Out-Null
    }
})
# The form's CLOSE button and Escape/Alt+F4 work in C# even if this callback fails.
$script:coverForm.Add_Dismissed({
    $script:coverActive = $false
    $script:coverButton.Text = if ($script:isActive) { 'FULL COVER' } else { 'TEST FULL COVER' }
})
$script:hideButton.Add_Click({ $script:panel.Hide() })
$script:panel.Add_RestorePressed({ Restore-Privacy; $script:panel.Show(); $script:panel.Activate() })
$script:panel.Add_ShowControlsPressed({ $script:panel.Show(); $script:panel.WindowState = 'Normal'; $script:panel.Activate() })
function Register-FallbackHotkey {
    param(
        [int]$id,
        [object[]]$choices
    )
    foreach ($choice in $choices) {
        if ([PulsePrivacy.Native]::RegisterHotKey($script:panel.Handle, $id, [uint32]$choice.Modifiers, [uint32]$choice.Key)) {
            $script:hotkeys += $id
            return [string]$choice.Name
        }
    }
    return ''
}
$script:panel.Add_Shown({
    # MOD_ALT=1, MOD_CONTROL=2, MOD_SHIFT=4; virtual keys P=0x50, C=0x43,
    # F11=0x7A and F12=0x7B. These are system-wide when successfully registered.
    $script:restoreHotkeyName = Register-FallbackHotkey 1 @(
        @{ Name='Ctrl + Alt + Shift + P'; Modifiers=7; Key=0x50 },
        @{ Name='Ctrl + Shift + F11'; Modifiers=6; Key=0x7A },
        @{ Name='Ctrl + Alt + F11'; Modifiers=3; Key=0x7A },
        @{ Name='Ctrl + Alt + Shift + F11'; Modifiers=7; Key=0x7A }
    )
    $script:showHotkeyName = Register-FallbackHotkey 2 @(
        @{ Name='Ctrl + Alt + Shift + C'; Modifiers=7; Key=0x43 },
        @{ Name='Ctrl + Shift + F12'; Modifiers=6; Key=0x7B },
        @{ Name='Ctrl + Alt + F12'; Modifiers=3; Key=0x7B },
        @{ Name='Ctrl + Alt + Shift + F12'; Modifiers=7; Key=0x7B }
    )
    if ($script:restoreHotkeyName) {
        $script:restoreHotkeyLabel.Text = 'Emergency restore: ' + $script:restoreHotkeyName
    } else {
        $script:restoreHotkeyLabel.Text = 'Emergency restore: RESTORE DESKTOP button only'
    }
    if ($script:showHotkeyName) {
        $script:showHotkeyLabel.Text = 'Show controls: ' + $script:showHotkeyName
    } else {
        $script:showHotkeyLabel.Text = 'Show controls: unavailable - keep controls visible'
    }
    if (-not $script:restoreHotkeyName -or -not $script:showHotkeyName) {
        # Native CLOSE / Esc / Alt+F4 on the cover are available regardless of
        # shortcut registration. Only disabling Hide Controls is necessary.
        $script:hideButton.Enabled = $false
        $script:statusLabel.Text = 'Hotkeys unavailable - keep controls open'
    }
})
$script:panel.Add_FormClosing({
    Restore-Privacy
    foreach ($key in $script:hotkeys) { [void][PulsePrivacy.Native]::UnregisterHotKey($script:panel.Handle,$key) }
})

try {
    [System.Windows.Forms.Application]::EnableVisualStyles()
    [System.Windows.Forms.Application]::Run($script:panel)
} finally {
    try { Restore-Privacy } catch { }
    if ($script:coverForm) { $script:coverForm.Dispose() }
    if ($script:backgroundForm) { $script:backgroundForm.Dispose() }
    if ($script:imageBitmap) { $script:imageBitmap.Dispose() }
}
