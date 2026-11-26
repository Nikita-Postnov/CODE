// NP Punto Browser Native Messaging host. Receives ONLY desired language ("ru"/"en").
// No typed characters, clipboard contents or web addresses are transmitted.
// Build as a .NET Framework console executable using tools/install_np_punto_browser_bridge.ps1.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

internal static class PuntoLayoutHost
{
    private const int InputKeyboard = 1;
    private const uint KeyUp = 0x0002, Extended = 0x0001;
    private const ushort WinKey = 0x5B, SpaceKey = 0x20;
    private const int English = 0x0409, Russian = 0x0419;
    private const string ManifestFile = "com.npcore.punto_layout.json";

    [StructLayout(LayoutKind.Sequential)]
    internal struct KeyboardInput
    {
        public ushort Vk, Scan;
        public uint Flags, Time;
        public IntPtr Extra;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct MouseInput
    {
        public int Dx, Dy;
        public uint MouseData, Flags, Time;
        public IntPtr Extra;
    }

    [StructLayout(LayoutKind.Explicit)]
    internal struct InputData
    {
        [FieldOffset(0)] public KeyboardInput Keyboard;
        [FieldOffset(0)] public MouseInput Mouse;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct NativeInput
    {
        public uint Type;
        public InputData Data;
    }

    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr handle, out uint pid);
    [DllImport("user32.dll")] private static extern IntPtr GetKeyboardLayout(uint thread);
    [DllImport("user32.dll")] private static extern int GetKeyboardLayoutList(int count, [Out] IntPtr[] layouts);
    [DllImport("user32.dll")] private static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll", SetLastError = true)] private static extern uint SendInput(
        uint count, [In] NativeInput[] inputs, int cbSize
    );

    private static NativeInput Key(ushort vk, bool up)
    {
        return new NativeInput {
            Type = InputKeyboard,
            Data = new InputData {
                Keyboard = new KeyboardInput {
                    Vk = vk, Flags = (up ? KeyUp : 0) | (vk == WinKey ? Extended : 0)
                }
            }
        };
    }

    private static bool ReadExactly(Stream source, byte[] buffer, int length)
    {
        int offset = 0;
        while (offset < length) {
            int received = source.Read(buffer, offset, length - offset);
            if (received <= 0) return false;
            offset += received;
        }
        return true;
    }

    private static string Receive()
    {
        Stream input = Console.OpenStandardInput();
        byte[] header = new byte[4];
        if (!ReadExactly(input, header, 4)) return null;
        int size = BitConverter.ToInt32(header, 0);
        if (size < 2 || size > 4096) return null;
        byte[] body = new byte[size];
        if (!ReadExactly(input, body, size)) return null;
        return new UTF8Encoding(false, true).GetString(body);
    }

    private static void Reply(string status)
    {
        var serializer = new JavaScriptSerializer();
        byte[] body = Encoding.UTF8.GetBytes(serializer.Serialize(new Dictionary<string, object> {
            { "ok", status == "switched" || status == "already" },
            { "status", status }
        }));
        Stream output = Console.OpenStandardOutput();
        byte[] header = BitConverter.GetBytes(body.Length);
        output.Write(header, 0, header.Length);
        output.Write(body, 0, body.Length);
        output.Flush();
    }

    private static bool CallerAllowed(string[] args)
    {
        if (args.Length == 0) return false;
        string origin = args[0];
        if (!System.Text.RegularExpressions.Regex.IsMatch(
            origin, @"^chrome-extension://[a-p]{32}/$"
        )) return false;
        string file = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ManifestFile);
        if (!File.Exists(file)) return false;
        var manifest = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
            File.ReadAllText(file, Encoding.UTF8)
        );
        object raw;
        if (!manifest.TryGetValue("allowed_origins", out raw)) return false;
        var allowed = raw as System.Collections.IEnumerable;
        if (allowed == null || raw is string) return false;
        foreach (object entry in allowed) {
            if (String.Equals(entry as string, origin, StringComparison.Ordinal)) return true;
        }
        return false;
    }

    private static bool ExactlyTwoLanguages()
    {
        if (GetKeyboardLayoutList(0, null) != 2) return false;
        IntPtr[] layouts = new IntPtr[2];
        if (GetKeyboardLayoutList(2, layouts) != 2) return false;
        int a = unchecked((int)layouts[0].ToInt64()) & 0xffff;
        int b = unchecked((int)layouts[1].ToInt64()) & 0xffff;
        return (a == English && b == Russian) || (a == Russian && b == English);
    }

    private static bool ModifiersPressed()
    {
        foreach (int key in new int[] { 0x10, 0x11, 0x12, 0x5B, 0x5C }) {
            if ((GetAsyncKeyState(key) & 0x8000) != 0) return true;
        }
        return false;
    }

    private static string SwitchLanguage(string target)
    {
        if (target != "ru" && target != "en") return "invalid";
        if (!ExactlyTwoLanguages()) return "layouts_unsupported";
        IntPtr foreground = GetForegroundWindow();
        if (foreground == IntPtr.Zero) return "no_foreground";
        uint pid;
        uint tid = GetWindowThreadProcessId(foreground, out pid);
        if (tid == 0 || pid == 0) return "no_foreground";
        string process;
        try {
            process = Process.GetProcessById((int)pid).ProcessName.ToLowerInvariant();
        } catch {
            return "no_foreground";
        }
        // Prevent changing the layout in an unrelated application.
        if (Array.IndexOf(new string[] {
            "chrome", "msedge", "brave", "vivaldi", "opera", "browser", "yandex"
        }, process) < 0) return "not_browser";
        int requested = target == "ru" ? Russian : English;
        if ((unchecked((int)GetKeyboardLayout(tid).ToInt64()) & 0xffff) == requested)
            return "already";
        if (ModifiersPressed()) return "modifiers_held";
        if (GetForegroundWindow() != foreground) return "focus_changed";

        var events = new NativeInput[] {
            Key(WinKey, false), Key(SpaceKey, false),
            Key(SpaceKey, true), Key(WinKey, true)
        };
        uint sent = SendInput((uint)events.Length, events,
            Marshal.SizeOf(typeof(NativeInput)));
        if (sent != (uint)events.Length) {
            // Even partial SendInput must not leave the synthetic Win key held.
            SendInput(2, new NativeInput[] {
                Key(SpaceKey, true), Key(WinKey, true)
            }, Marshal.SizeOf(typeof(NativeInput)));
            return "send_input_failed";
        }
        for (int attempt = 0; attempt < 12; ++attempt) {
            Thread.Sleep(25);
            if (GetForegroundWindow() != foreground) return "focus_changed";
            if ((unchecked((int)GetKeyboardLayout(tid).ToInt64()) & 0xffff) == requested)
                return "switched";
        }
        return "not_confirmed";
    }

    private static int Main(string[] args)
    {
        try {
            if (args.Length == 1 && args[0] == "--self-test") {
                int actualSize = Marshal.SizeOf(typeof(NativeInput));
                int requiredSize = IntPtr.Size == 8 ? 40 : 28;
                if (actualSize != requiredSize) {
                    Console.Error.WriteLine("INVALID_WIN32_INPUT_SIZE=" + actualSize + "; EXPECTED=" + requiredSize);
                    return 1;
                }
                Console.WriteLine("WIN32_INPUT_SIZE=" + actualSize);
                Console.WriteLine("NP_PUNTO_NATIVE_HOST_SELF_TEST_PASS");
                return 0;
            }
            if (!CallerAllowed(args)) {
                Reply("unauthorized");
                return 1;
            }
            string json = Receive();
            if (json == null) {
                Reply("invalid");
                return 1;
            }
            var message = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(json);
            object action, lang;
            if (!message.TryGetValue("action", out action)) {
                Reply("invalid");
                return 1;
            }
            if (String.Equals(action as string, "ping", StringComparison.Ordinal)) {
                Reply("ready");
                return 0;
            }
            if (!String.Equals(action as string, "switch", StringComparison.Ordinal) ||
                !message.TryGetValue("language", out lang)) {
                Reply("invalid");
                return 1;
            }
            Reply(SwitchLanguage(lang as string));
            return 0;
        }
        catch {
            // Never put diagnostic output on native messaging STDOUT.
            try { Reply("failed"); } catch { }
            return 1;
        }
    }
}
