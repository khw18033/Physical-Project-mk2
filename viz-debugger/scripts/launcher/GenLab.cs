// gen-lab-server.exe — 저장소 최상단에서 더블클릭하면 생성 서비스(gen-lab · 8802)만 띄운다 (261123).
//
// GPU 가 큰 PC 에 생성을 맡길 때 그 PC 에서 쓴다. 노트북 화면은 발화 판의 「생성 서비스 주소」 칸에 이 창이 알려 주는
// 주소를 넣는다(gen-lab/README.md 「GPU 가 큰 다른 PC 에 생성을 맡길 때」).
//
//  1. gen-lab\.venv 가 없으면 만들고 requirements.txt 를 깐다
//  2. llama.cpp(GPU 가 있으면 CUDA 빌드) · 가중치가 없으면 받는다 — GPU 메모리 8 GB 이상이면 Qwen3 8B, 아니면 4B
//  3. 듣는 주소: 환경변수 GEN_LAB_HOST 가 있으면 그것, 없으면 이 PC 의 Tailscale IPv4, 그것도 없으면 127.0.0.1
//     (`--local` 을 주면 무조건 127.0.0.1)
//  4. python -m server.main — 창을 닫으면 llama-server 까지 함께 내려간다
//
// 빌드 (Windows 기본 .NET Framework 컴파일러, 저장소 최상단에서):
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /codepage:65001 /out:gen-lab-server.exe viz-debugger\scripts\launcher\GenLab.cs
using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;

[assembly: AssemblyTitle("gen-lab server launcher")]
[assembly: AssemblyDescription("Runs the gen-lab generation service (8802) on this PC")]
[assembly: AssemblyProduct("hybrid-dt gen-lab")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

class GenLab
{
    // gen-lab 과 같은 환경변수를 읽는다(server/main.py 의 VIZ_GENERATE_PORT) — 창에 적는 주소가 실제 포트와 같아야 한다.
    static readonly int Port = PortFromEnv();

    static int PortFromEnv()
    {
        int value;
        return int.TryParse(Environment.GetEnvironmentVariable("VIZ_GENERATE_PORT"), out value) && value > 0 ? value : 8802;
    }
    const int LlamaPort = 8803;

    static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        Console.Title = "gen-lab (생성 서비스 8802)";

        string genLab = FindGenLab(AppDomain.CurrentDomain.BaseDirectory);
        if (genLab == null) return Fail("gen-lab 폴더를 찾지 못했습니다. gen-lab-server.exe 를 저장소 최상단에 두세요.");
        Say("폴더: " + genLab);

        if (PortOpen("127.0.0.1", Port))
            Say("경고: " + Port + " 를 이미 누가 쓰고 있습니다 — viz-dev.exe(npm run dev)가 생성 서비스를 같이 띄웠을 수 있습니다. 그 창을 닫고 다시 실행하세요.");
        if (PortOpen("127.0.0.1", LlamaPort))
            Say("경고: 8803 에 남은 llama-server 가 있습니다. 작업 관리자에서 llama-server.exe 를 끄고 다시 실행하세요 (README 「유령 llama-server」).");

        if (!EnsurePythonService(genLab)) return Fail("파이썬 환경을 준비하지 못했습니다. 위 출력이 사유입니다.");
        EnsureLlama(genLab);

        bool localOnly = Array.IndexOf(args, "--local") >= 0;
        string host = Environment.GetEnvironmentVariable("GEN_LAB_HOST");
        if (localOnly) host = "127.0.0.1";
        else if (string.IsNullOrEmpty(host)) host = TailscaleIp() ?? "127.0.0.1";

        Console.WriteLine();
        Console.WriteLine("==========================================================");
        if (host == "127.0.0.1")
        {
            Console.WriteLine("  이 PC 안에서만 받습니다 (127.0.0.1:" + Port + ")");
            if (!localOnly) Console.WriteLine("  Tailscale 주소를 찾지 못했습니다 — 다른 PC 에서 부르려면 Tailscale 을 켜고 다시 실행하세요.");
        }
        else
        {
            Console.WriteLine("  노트북 화면의 「생성 서비스 주소」 칸에 넣을 주소:");
            Console.WriteLine();
            Console.WriteLine("      http://" + host + ":" + Port);
            Console.WriteLine();
            Console.WriteLine("  (이 주소에서만 받습니다 — tailnet 밖에서는 닿지 않습니다)");
        }
        Console.WriteLine("  끄려면 이 창을 닫으세요. llama-server 도 함께 내려갑니다.");
        Console.WriteLine("==========================================================");
        Console.WriteLine();

        string python = Path.Combine(genLab, ".venv", "Scripts", "python.exe");
        var psi = new ProcessStartInfo(python, "-m server.main") { WorkingDirectory = genLab, UseShellExecute = false };
        psi.EnvironmentVariables["GEN_LAB_HOST"] = host;
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        Process server = Process.Start(psi);
        Job.Add(server);
        server.WaitForExit();
        if (server.ExitCode != 0) return Fail("생성 서비스가 종료되었습니다 (코드 " + server.ExitCode + ")");
        return 0;
    }

    static string FindGenLab(string start)
    {
        for (var d = new DirectoryInfo(start); d != null; d = d.Parent)
        {
            string candidate = Path.Combine(d.FullName, "gen-lab");
            if (File.Exists(Path.Combine(candidate, "server", "main.py"))) return candidate;
        }
        return null;
    }

    // `tailscale ip -4` 의 첫 줄. Tailscale 이 없거나 꺼져 있으면 null.
    static string TailscaleIp()
    {
        foreach (string exe in new[] { "tailscale", Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Tailscale", "tailscale.exe") })
        {
            string output = RunCapture(exe, "ip -4");
            if (output == null || lastExit != 0) continue;
            foreach (string line in output.Split('\n'))
            {
                string ip = line.Trim();
                if (ip.StartsWith("100.")) return ip;
            }
        }
        return null;
    }

    // ── 파이썬 환경 · llama.cpp · 가중치 (viz-dev.exe 의 VizDev.cs 와 같은 절차) ──────────────

    static bool EnsurePythonService(string serviceDir)
    {
        string req = Path.Combine(serviceDir, "requirements.txt");
        if (!File.Exists(req)) return false;
        string venvPython = Path.Combine(serviceDir, ".venv", "Scripts", "python.exe");
        // 표지 파일은 viz-dev.exe 와 같은 이름이다 — 어느 런처로 깔았든 다른 런처가 다시 깔지 않게.
        string stamp = Path.Combine(serviceDir, ".venv", "viz-dev-installed.txt");
        string wanted = File.ReadAllText(req);
        if (File.Exists(venvPython) && File.Exists(stamp) && File.ReadAllText(stamp) == wanted) return true;

        Say("파이썬 환경을 준비합니다 (" + serviceDir + "\\.venv) — 처음 한 번은 몇 분 걸립니다.");
        if (!File.Exists(venvPython))
        {
            string[] basePython = FindBasePython();
            if (basePython == null)
            {
                Say("64비트 Python 3.10~3.13 을 찾지 못했습니다. https://www.python.org 에서 설치한 뒤 다시 실행하세요.");
                return false;
            }
            if (RunExe(basePython[0], basePython[1] + " -m venv .venv", serviceDir) != 0 || !File.Exists(venvPython)) return false;
        }
        if (RunExe(venvPython, "-m pip install --disable-pip-version-check -r requirements.txt", serviceDir) != 0) return false;
        File.WriteAllText(stamp, wanted);
        return true;
    }

    static string[] FindBasePython()
    {
        foreach (string v in new[] { "3.12", "3.11", "3.10", "3.13" })
            if (RunQuiet("py", "-" + v + " -c \"import struct,sys; sys.exit(struct.calcsize('P') != 8)\"") == 0)
                return new[] { "py", "-" + v };
        if (RunQuiet("python", "-c \"import struct,sys; sys.exit(not ((3,10) <= sys.version_info[:2] <= (3,13) and struct.calcsize('P') == 8))\"") == 0)
            return new[] { "python", "" };
        return null;
    }

    const string LlamaRelease = "https://github.com/ggml-org/llama.cpp/releases/download/b10825/";
    const string Model8B = "Qwen3-8B-Q4_K_M.gguf";
    const string Model4B = "Qwen3-4B-Q4_K_M.gguf";

    static void EnsureLlama(string genLab)
    {
        string llamaDir = Path.Combine(genLab, "vendor", "llama.cpp");
        bool gpu = RunQuiet("nvidia-smi", "-L") == 0;
        if (!File.Exists(Path.Combine(llamaDir, "llama-server.exe")))
        {
            Say("llama.cpp (" + (gpu ? "CUDA" : "CPU") + " 빌드) 를 받습니다...");
            Directory.CreateDirectory(llamaDir);
            var zips = gpu
                ? new[] { "llama-b10825-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip" }
                : new[] { "llama-b10825-bin-win-cpu-x64.zip" };
            foreach (string zip in zips)
            {
                string local = Path.Combine(genLab, "vendor", zip);
                if (!Download(LlamaRelease + zip, local) || RunExe("tar", "-xf \"" + local + "\" -C \"" + llamaDir + "\"", genLab) != 0)
                {
                    Say("경고: llama.cpp 를 받지 못했습니다 — 생성은 스텁으로 뜹니다.");
                    return;
                }
                File.Delete(local);
            }
        }

        string models = Path.Combine(genLab, "models");
        Directory.CreateDirectory(models);
        if (Directory.GetFiles(models, "*.gguf").Length > 0) return;
        // 측정한 모델은 8B 다(gen-lab/runs). 8B 는 GPU 메모리 약 7 GB 를 쓰므로 그만한 GPU 에서만 받는다.
        int vramMib = GpuMemoryMib();
        string name = vramMib >= 8000 ? Model8B : Model4B;
        string repo = name == Model8B ? "Qwen/Qwen3-8B-GGUF" : "Qwen/Qwen3-4B-GGUF";
        Say("생성 가중치 " + name + " 를 받습니다 (GPU 메모리 " + (vramMib > 0 ? vramMib + " MiB" : "모름") + ") — 한 번만 받습니다.");
        if (!Download("https://huggingface.co/" + repo + "/resolve/main/" + name, Path.Combine(models, name)))
            Say("경고: 가중치를 받지 못했습니다 — 생성은 스텁으로 뜹니다.");
    }

    // 가장 큰 GPU 의 메모리(MiB). 모르면 0.
    static int GpuMemoryMib()
    {
        string output = RunCapture("nvidia-smi", "--query-gpu=memory.total --format=csv,noheader,nounits");
        if (output == null || lastExit != 0) return 0;
        int best = 0;
        foreach (string line in output.Split('\n'))
        {
            int value;
            if (int.TryParse(line.Trim(), out value) && value > best) best = value;
        }
        return best;
    }

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
        return RunCapture(file, args) == null ? -1 : lastExit;
    }

    static int lastExit;

    // 출력을 받아 돌려준다. 실행 자체를 못 했으면 null 이고, 실행했으면 종료 코드는 `lastExit` 에 남는다.
    static string RunCapture(string file, string args)
    {
        try
        {
            var psi = new ProcessStartInfo(file, args) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
            Process p = Process.Start(psi);
            string output = p.StandardOutput.ReadToEnd();
            p.StandardError.ReadToEnd();
            p.WaitForExit();
            lastExit = p.ExitCode;
            return output;
        }
        catch (System.ComponentModel.Win32Exception) { return null; }
    }

    // 런처가 어떻게 끝나든 자식(gen-lab · llama-server)이 남지 않게 한 Job 에 묶는다 (VizDev.cs 와 같다).
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
            SetInformationJobObject(h, 9, ref info, Marshal.SizeOf(typeof(ExtendedLimits)));
            return h;
        }

        public static void Add(Process p)
        {
            if (handle != IntPtr.Zero) AssignProcessToJobObject(handle, p.Handle);
        }
    }

    static bool PortOpen(string host, int port)
    {
        try
        {
            using (var c = new TcpClient())
            {
                IAsyncResult r = c.BeginConnect(host, port, null, null);
                bool ok = r.AsyncWaitHandle.WaitOne(300) && c.Connected;
                if (ok) c.EndConnect(r);
                return ok;
            }
        }
        catch { return false; }
    }

    static void Say(string msg)
    {
        Console.WriteLine("[gen-lab] " + msg);
    }

    static int Fail(string msg)
    {
        Console.WriteLine();
        Say(msg);
        Say("아무 키나 누르면 창이 닫힙니다.");
        try { Console.ReadKey(true); } catch (InvalidOperationException) { }
        return 1;
    }
}
