// viz-dev.exe — 저장소 최상단에서 더블클릭하면 viz-debugger 의 `npm run dev` 를 띄우고
// 웹(http://localhost:5174/)이 열리면 브라우저를 연다.
//
// 빌드 (Windows 기본 .NET Framework 컴파일러, 저장소 최상단에서):
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /codepage:65001 /out:viz-dev.exe viz-debugger\scripts\launcher\VizDev.cs
//
// 끄기: 이 창을 닫거나 Ctrl+C. 자식 프로세스(게이트웨이 · Vite · STT · 생성)는 같은 콘솔에 붙어 있어 함께 닫힌다.
using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

[assembly: AssemblyTitle("viz-debugger dev launcher")]
[assembly: AssemblyDescription("Runs npm run dev in viz-debugger and opens the browser")]
[assembly: AssemblyProduct("hybrid-dt viz-debugger")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

class VizDev
{
    const int WebPort = 5174;
    const string WebUrl = "http://localhost:5174/";

    static int Main()
    {
        Console.OutputEncoding = Encoding.UTF8;
        Console.Title = "viz-debugger (npm run dev)";

        string dir = FindVizDebugger(AppDomain.CurrentDomain.BaseDirectory);
        if (dir == null) return Fail("viz-debugger 폴더를 찾지 못했습니다. viz-dev.exe 를 저장소 최상단에 두세요.");

        string npm = FindNpm();
        if (npm == null) return Fail("npm 을 찾지 못했습니다. Node.js 를 설치하세요 (https://nodejs.org).");

        Console.WriteLine("[viz-dev] 폴더: " + dir);
        Console.WriteLine("[viz-dev] npm : " + npm);

        if (!Directory.Exists(Path.Combine(dir, "node_modules")))
        {
            Console.WriteLine("[viz-dev] node_modules 가 없어 npm install 을 먼저 실행합니다...");
            if (Run(npm, "install", dir) != 0) return Fail("npm install 실패");
        }

        // STT·생성은 `npm run dev` 가 "환경이 있으면" 띄운다 (dev-stt.mjs · dev-generate.mjs).
        // 더블클릭으로 쓰는 사람은 README 의 준비 절차를 안 거치므로, 그 절차를 여기서 대신한다.
        // 실패해도 화면은 띄운다 — 두 서비스는 없어도 되는 프로세스다.
        EnsurePythonService("stt", Path.Combine(dir, "stt"));
        string genLab = Path.Combine(Path.GetDirectoryName(dir), "gen-lab");
        if (EnsurePythonService("generate", genLab)) EnsureLlama(genLab);

        if (PortOpen(WebPort))
            Console.WriteLine("[viz-dev] 경고: " + WebPort + " 포트가 이미 사용 중입니다. 이전 실행이 남아 있을 수 있습니다.");

        Console.WriteLine("[viz-dev] npm run dev 시작 — 끄려면 이 창을 닫으세요.");
        Console.WriteLine();

        Process dev = Start(npm, "run dev", dir);
        new Thread(() => OpenBrowserWhenReady(dev)) { IsBackground = true }.Start();
        dev.WaitForExit();

        if (dev.ExitCode != 0) return Fail("npm run dev 가 종료되었습니다 (코드 " + dev.ExitCode + ")");
        return 0;
    }

    static string FindVizDebugger(string start)
    {
        for (var d = new DirectoryInfo(start); d != null; d = d.Parent)
        {
            string candidate = Path.Combine(d.FullName, "viz-debugger");
            if (File.Exists(Path.Combine(candidate, "package.json"))) return candidate;
        }
        return null;
    }

    // npm 은 Node 설치 폴더의 `node_modules\npm\bin\npm-cli.js` 다. npm.cmd(배치 파일)를 거치지 않고
    // node.exe 로 그것을 직접 돌린다 — cmd.exe 를 끼우면 Ctrl+C 때 "일괄 작업을 끝내시겠습니까" 가 뜨고
    // 백신이 런처를 의심하기도 한다.
    static string FindNpm()
    {
        var dirs = new System.Collections.Generic.List<string>();
        foreach (string p in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
            if (p.Trim().Length > 0) dirs.Add(p.Trim().Trim('"'));
        foreach (string root in new[] {
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
            Environment.GetEnvironmentVariable("ProgramW6432"),
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86) })
            if (!string.IsNullOrEmpty(root)) dirs.Add(Path.Combine(root, "nodejs"));

        foreach (string d in dirs)
        {
            try
            {
                string node = Path.Combine(d, "node.exe");
                string cli = Path.Combine(d, "node_modules", "npm", "bin", "npm-cli.js");
                if (File.Exists(node) && File.Exists(cli)) return cli;
            }
            catch (ArgumentException) { }
        }
        return null;
    }

    static Process Start(string npmCli, string args, string cwd)
    {
        string nodeDir = Path.GetFullPath(Path.Combine(Path.GetDirectoryName(npmCli), "..", "..", ".."));
        var psi = new ProcessStartInfo(Path.Combine(nodeDir, "node.exe"), "\"" + npmCli + "\" " + args)
        {
            WorkingDirectory = cwd,
            UseShellExecute = false,
        };
        // npm 이 띄우는 하위 셸도 node 를 찾도록 그 폴더를 PATH 앞에 둔다 (PATH 에 Node 가 없을 때 대비).
        psi.EnvironmentVariables["PATH"] = nodeDir + ";" + psi.EnvironmentVariables["PATH"];
        Process p = Process.Start(psi);
        Job.Add(p);
        return p;
    }

    // ── STT · 생성 환경 ───────────────────────────────────────────────────────

    // `<서비스 폴더>\.venv` 를 만들고 requirements.txt 를 깐다. dev-stt.mjs · dev-generate.mjs 가
    // 찾는 자리가 정확히 그것이다. 설치가 끝까지 된 requirements 를 표지 파일에 적어 두어,
    // 같으면 다음 실행부터는 건너뛰고 · 바뀌었거나 중간에 끊겼으면 다시 깐다.
    static bool EnsurePythonService(string name, string serviceDir)
    {
        string req = Path.Combine(serviceDir, "requirements.txt");
        if (!File.Exists(req)) return false;
        string venvPython = Path.Combine(serviceDir, ".venv", "Scripts", "python.exe");
        string stamp = Path.Combine(serviceDir, ".venv", "viz-dev-installed.txt");
        string wanted = File.ReadAllText(req);
        if (File.Exists(venvPython) && File.Exists(stamp) && File.ReadAllText(stamp) == wanted) return true;

        Console.WriteLine("[viz-dev] " + name + " 파이썬 환경을 준비합니다 (" + serviceDir + "\\.venv) — 처음 한 번은 몇 분 걸립니다.");
        if (!File.Exists(venvPython))
        {
            string[] basePython = FindBasePython();
            if (basePython == null)
            {
                Warn(name, "64비트 Python 3.10~3.13 을 찾지 못했습니다. https://www.python.org 에서 설치한 뒤 다시 실행하세요.");
                return false;
            }
            if (RunExe(basePython[0], basePython[1] + " -m venv .venv", serviceDir) != 0 || !File.Exists(venvPython))
            {
                Warn(name, "가상환경을 만들지 못했습니다.");
                return false;
            }
        }
        if (RunExe(venvPython, "-m pip install --disable-pip-version-check -r requirements.txt", serviceDir) != 0)
        {
            Warn(name, "pip install 이 실패했습니다. 위 출력 끝줄이 사유입니다.");
            return false;
        }
        File.WriteAllText(stamp, wanted);
        return true;
    }

    // ctranslate2(STT) 휠이 있는 판만 고른다. 너무 새 판(3.14~)은 휠이 없어 설치가 실패한다.
    static string[] FindBasePython()
    {
        foreach (string v in new[] { "3.12", "3.11", "3.10", "3.13" })
            if (RunQuiet("py", "-" + v + " -c \"import struct,sys; sys.exit(struct.calcsize('P') != 8)\"") == 0)
                return new[] { "py", "-" + v };
        if (RunQuiet("python", "-c \"import struct,sys; sys.exit(not ((3,10) <= sys.version_info[:2] <= (3,13) and struct.calcsize('P') == 8))\"") == 0)
            return new[] { "python", "" };
        return null;
    }

    // 생성은 venv 만으로는 **스텁**이다. llama-server 바이너리와 가중치가 있어야 실제 모델이 답한다
    // (README 「생성」). 없으면 받는다 — GPU 가 있으면 CUDA 빌드, 없으면 CPU 빌드, 가중치는 Qwen3 4B.
    const string LlamaRelease = "https://github.com/ggml-org/llama.cpp/releases/download/b10825/";
    const string ModelUrl = "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf";

    static void EnsureLlama(string genLab)
    {
        string llamaDir = Path.Combine(genLab, "vendor", "llama.cpp");
        if (!File.Exists(Path.Combine(llamaDir, "llama-server.exe")))
        {
            bool gpu = RunQuiet("nvidia-smi", "-L") == 0;
            Console.WriteLine("[viz-dev] llama.cpp (" + (gpu ? "CUDA" : "CPU") + " 빌드) 를 받습니다...");
            Directory.CreateDirectory(llamaDir);
            var zips = gpu
                ? new[] { "llama-b10825-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip" }
                : new[] { "llama-b10825-bin-win-cpu-x64.zip" };
            foreach (string zip in zips)
            {
                string local = Path.Combine(genLab, "vendor", zip);
                if (!Download(LlamaRelease + zip, local) || RunExe("tar", "-xf \"" + local + "\" -C \"" + llamaDir + "\"", genLab) != 0)
                {
                    Warn("generate", "llama.cpp 를 받지 못했습니다 — 생성은 스텁으로 뜹니다.");
                    return;
                }
                File.Delete(local);
            }
        }

        string models = Path.Combine(genLab, "models");
        Directory.CreateDirectory(models);
        if (Directory.GetFiles(models, "*.gguf").Length == 0)
        {
            Console.WriteLine("[viz-dev] 생성 가중치 Qwen3-4B-Q4_K_M.gguf (2.5 GB) 를 받습니다 — 한 번만 받습니다.");
            if (!Download(ModelUrl, Path.Combine(models, "Qwen3-4B-Q4_K_M.gguf")))
                Warn("generate", "가중치를 받지 못했습니다 — 생성은 스텁으로 뜹니다.");
        }
    }

    // 받는 중에는 `.part` 로 두고, 끝까지 받았을 때만 이름을 바꾼다 — 끊긴 파일을 완성본으로 읽지 않게.
    static bool Download(string url, string target)
    {
        string part = target + ".part";
        if (RunExe("curl.exe", "-L --fail -C - -o \"" + part + "\" \"" + url + "\"", Path.GetDirectoryName(target)) != 0) return false;
        if (File.Exists(target)) File.Delete(target);
        File.Move(part, target);
        return true;
    }

    static int RunExe(string file, string args, string cwd)
    {
        try
        {
            Process p = Process.Start(new ProcessStartInfo(file, args) { WorkingDirectory = cwd, UseShellExecute = false });
            Job.Add(p);
            p.WaitForExit();
            return p.ExitCode;
        }
        catch (System.ComponentModel.Win32Exception) { return -1; }
    }

    static int RunQuiet(string file, string args)
    {
        try
        {
            var psi = new ProcessStartInfo(file, args) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
            Process p = Process.Start(psi);
            p.StandardOutput.ReadToEnd();
            p.StandardError.ReadToEnd();
            p.WaitForExit();
            return p.ExitCode;
        }
        catch (System.ComponentModel.Win32Exception) { return -1; }
    }

    static void Warn(string name, string msg)
    {
        Console.WriteLine("[viz-dev] 경고(" + name + "): " + msg);
        Console.WriteLine("[viz-dev]   화면은 그대로 띄우고 그 기능만 꺼집니다. 다음 실행 때 다시 시도합니다.");
    }

    // 런처가 어떻게 끝나든(창 닫기 · 강제 종료) 자식들이 남지 않게 한 Job 에 묶는다.
    // 런처가 죽으면 Job 핸들이 닫히고, KILL_ON_JOB_CLOSE 로 그 안의 프로세스 트리가 전부 끝난다.
    // 남은 게이트웨이가 8790 을 쥐고 있으면 다음 실행이 바로 죽는다 (dev-all.mjs 참고).
    static class Job
    {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr a, string name);
        [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr job, int cls, ref ExtendedLimits info, int size);
        [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        [StructLayout(LayoutKind.Sequential)]
        struct ExtendedLimits
        {
            public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass, SchedulingClass;
            public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
            public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
        }

        static readonly IntPtr handle = Create();

        static IntPtr Create()
        {
            IntPtr h = CreateJobObject(IntPtr.Zero, null);
            var info = new ExtendedLimits { LimitFlags = 0x2000 }; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            SetInformationJobObject(h, 9, ref info, Marshal.SizeOf(typeof(ExtendedLimits))); // JobObjectExtendedLimitInformation
            return h;
        }

        public static void Add(Process p)
        {
            if (handle != IntPtr.Zero) AssignProcessToJobObject(handle, p.Handle);
        }
    }

    static int Run(string npm, string args, string cwd)
    {
        Process p = Start(npm, args, cwd);
        p.WaitForExit();
        return p.ExitCode;
    }

    static void OpenBrowserWhenReady(Process dev)
    {
        // 이미 떠 있던 포트에 속지 않도록 Vite 가 새로 뜰 시간을 조금 준다.
        Thread.Sleep(1500);
        for (int i = 0; i < 120 && !dev.HasExited; i++)
        {
            if (PortOpen(WebPort))
            {
                Console.WriteLine("[viz-dev] 브라우저를 엽니다: " + WebUrl);
                try { Process.Start(new ProcessStartInfo(WebUrl) { UseShellExecute = true }); }
                catch (Exception e) { Console.WriteLine("[viz-dev] 브라우저 열기 실패: " + e.Message); }
                return;
            }
            Thread.Sleep(500);
        }
    }

    static bool PortOpen(int port)
    {
        try
        {
            using (var c = new TcpClient())
            {
                IAsyncResult r = c.BeginConnect("127.0.0.1", port, null, null);
                bool ok = r.AsyncWaitHandle.WaitOne(300) && c.Connected;
                if (ok) c.EndConnect(r);
                return ok;
            }
        }
        catch { return false; }
    }

    static int Fail(string msg)
    {
        Console.WriteLine();
        Console.WriteLine("[viz-dev] " + msg);
        Console.WriteLine("[viz-dev] 아무 키나 누르면 창이 닫힙니다.");
        try { Console.ReadKey(true); } catch (InvalidOperationException) { }
        return 1;
    }
}
