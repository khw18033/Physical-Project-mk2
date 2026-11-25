using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 격자 위 D* Lite (Koenig &amp; Likhachev, 2002). 가상 평가의 "온보드 탐지 + 증분 재계획" 비교 조건용.
///
/// - 격자는 NavMesh에서 만든다: 칸 중심이 NavMesh 위면 통행 가능 (벽/가구에서 agent radius만큼 이미 떨어져 있음).
/// - 탐지한 장애물은 AddObstacle로 칸을 막고, 다음 Plan에서 바뀐 부분만 다시 계산한다.
/// - 8방향 이동, 대각선은 양옆 칸이 모두 비어 있을 때만. 결과 경로는 격자 시야선으로 줄인다.
/// </summary>
public class DStarLiteGridPlanner
{
    public float Cell { get; private set; }
    public int Width { get; private set; }
    public int Height { get; private set; }
    public double LastPlanMs { get; private set; }
    public double InitMs { get; private set; }
    public int LastExpanded { get; private set; }
    public string LastStatus { get; private set; } = "";
    public int FreeCells { get; private set; }

    private Vector3 origin;      // 칸 (0,0)의 중심
    private float planeY;
    private bool[] staticFree;   // NavMesh 기준 통행 가능
    private bool[] blocked;      // 현재 막힌 칸 (정적 + 탐지한 장애물)
    // 비용은 정수(직선 1000, 대각선 1414)로 둔다. 실수 합은 같은 값이 미세하게 달라져 우선순위 비교가 틀어진다.
    private long[] g, rhs;
    private long km;
    private int start, goal, last;
    private bool initialized;

    private struct Key : IComparable<Key>
    {
        public long k1, k2; public int id;
        public int CompareTo(Key o)
        {
            int c = k1.CompareTo(o.k1); if (c != 0) return c;
            c = k2.CompareTo(o.k2); if (c != 0) return c;
            return id.CompareTo(o.id);
        }
    }
    private readonly SortedSet<Key> open = new SortedSet<Key>();
    private Key[] keyOf;
    private bool[] inOpen;
    private readonly List<int> pendingChanged = new List<int>();

    private static readonly int[] DX = { 1, -1, 0, 0, 1, 1, -1, -1 };
    private static readonly int[] DZ = { 0, 0, 1, -1, 1, -1, 1, -1 };
    private const long Inf = long.MaxValue / 4;
    private const long Straight = 1000, Diagonal = 1414;

    public void Build(float cell)
    {
        Cell = cell;
        NavMeshTriangulation tri = NavMesh.CalculateTriangulation();
        Vector3 min = new Vector3(float.MaxValue, 0f, float.MaxValue), max = new Vector3(float.MinValue, 0f, float.MinValue);
        float ySum = 0f;
        foreach (Vector3 v in tri.vertices)
        {
            min.x = Mathf.Min(min.x, v.x); min.z = Mathf.Min(min.z, v.z);
            max.x = Mathf.Max(max.x, v.x); max.z = Mathf.Max(max.z, v.z);
            ySum += v.y;
        }
        planeY = tri.vertices.Length > 0 ? ySum / tri.vertices.Length : 0f;
        origin = new Vector3(min.x, planeY, min.z);
        Width = Mathf.CeilToInt((max.x - min.x) / cell) + 1;
        Height = Mathf.CeilToInt((max.z - min.z) / cell) + 1;
        int n = Width * Height;
        staticFree = new bool[n]; blocked = new bool[n];
        g = new long[n]; rhs = new long[n]; keyOf = new Key[n]; inOpen = new bool[n];
        for (int z = 0; z < Height; z++)
            for (int x = 0; x < Width; x++)
            {
                Vector3 c = Center(x + z * Width);
                bool free =
                    NavMesh.SamplePosition(c, out NavMeshHit hit, 0.3f, NavMesh.AllAreas) &&
                    (new Vector2(hit.position.x - c.x, hit.position.z - c.z)).magnitude < 0.005f;
                staticFree[x + z * Width] = free;
                if (free) FreeCells++;
            }
    }

    private Vector3 Center(int id) => new Vector3(origin.x + (id % Width) * Cell, planeY, origin.z + (id / Width) * Cell);

    private int CellOf(Vector3 p)
    {
        int x = Mathf.Clamp(Mathf.RoundToInt((p.x - origin.x) / Cell), 0, Width - 1);
        int z = Mathf.Clamp(Mathf.RoundToInt((p.z - origin.z) / Cell), 0, Height - 1);
        return x + z * Width;
    }

    // 막힌 칸이면 가장 가까운 빈 칸
    private int NearestFree(int id)
    {
        if (!blocked[id]) return id;
        int cx = id % Width, cz = id / Width;
        for (int r = 1; r < 40; r++)
        {
            int best = -1; float bd = float.MaxValue;
            for (int dz = -r; dz <= r; dz++)
                for (int dx = -r; dx <= r; dx++)
                {
                    if (Mathf.Max(Mathf.Abs(dx), Mathf.Abs(dz)) != r) continue;
                    int x = cx + dx, z = cz + dz;
                    if (x < 0 || z < 0 || x >= Width || z >= Height || blocked[x + z * Width]) continue;
                    float d = dx * dx + dz * dz;
                    if (d < bd) { bd = d; best = x + z * Width; }
                }
            if (best >= 0) return best;
        }
        return id;
    }

    /// <summary>run 시작: 탐지 장애물을 지우고 목표에서 처음 계산한다.</summary>
    public void BeginRun(Vector3 startPos, Vector3 goalPos)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        int n = Width * Height;
        for (int i = 0; i < n; i++) { blocked[i] = !staticFree[i]; g[i] = Inf; rhs[i] = Inf; inOpen[i] = false; }
        open.Clear(); pendingChanged.Clear();
        km = 0;
        goal = NearestFree(CellOf(goalPos));
        start = NearestFree(CellOf(startPos));
        last = start;
        rhs[goal] = 0;
        Insert(goal, CalcKey(goal));
        ComputeShortestPath();
        initialized = true;
        sw.Stop();
        InitMs = sw.Elapsed.TotalMilliseconds;
    }

    /// <summary>탐지한 장애물: 상자(축 정렬)에서 margin 안의 칸을 막는다. 다음 Plan에서 반영.</summary>
    public void AddObstacle(Vector3 center, Vector3 size, float margin)
    {
        float hx = size.x * 0.5f + margin, hz = size.z * 0.5f + margin;
        int x0 = Mathf.Max(0, Mathf.FloorToInt((center.x - hx - origin.x) / Cell));
        int x1 = Mathf.Min(Width - 1, Mathf.CeilToInt((center.x + hx - origin.x) / Cell));
        int z0 = Mathf.Max(0, Mathf.FloorToInt((center.z - hz - origin.z) / Cell));
        int z1 = Mathf.Min(Height - 1, Mathf.CeilToInt((center.z + hz - origin.z) / Cell));
        for (int z = z0; z <= z1; z++)
            for (int x = x0; x <= x1; x++)
            {
                int id = x + z * Width;
                Vector3 c = Center(id);
                if (blocked[id] || Mathf.Abs(c.x - center.x) > hx || Mathf.Abs(c.z - center.z) > hz) continue;
                blocked[id] = true;
                pendingChanged.Add(id);
            }
    }

    /// <summary>현재 위치에서 목표까지. 실패하면 null.</summary>
    public List<Vector3> Plan(Vector3 from, Vector3 goalPos)
    {
        if (!initialized) return null;
        var sw = System.Diagnostics.Stopwatch.StartNew();
        LastExpanded = 0;

        start = NearestFree(CellOf(from));
        if (pendingChanged.Count > 0)
        {
            km += H(last, start);
            last = start;
            foreach (int u in pendingChanged)
            {
                UpdateVertex(u);
                int ux = u % Width, uz = u / Width;
                for (int k = 0; k < 8; k++)
                {
                    int x = ux + DX[k], z = uz + DZ[k];
                    if (x < 0 || z < 0 || x >= Width || z >= Height) continue;
                    UpdateVertex(x + z * Width);
                }
            }
            pendingChanged.Clear();
        }
        ComputeShortestPath();

        List<Vector3> path = null;
        if (g[start] < Inf)
        {
            var cells = new List<int> { start };
            int cur = start;
            for (int guard = 0; cur != goal && guard < Width * Height; guard++)
            {
                int best = -1; long bc = Inf;
                int cx = cur % Width, cz = cur / Width;
                for (int k = 0; k < 8; k++)
                {
                    int x = cx + DX[k], z = cz + DZ[k];
                    if (x < 0 || z < 0 || x >= Width || z >= Height) continue;
                    int s = x + z * Width;
                    long c = Add(Cost(cur, s), g[s]);
                    if (c < bc) { bc = c; best = s; }
                }
                if (best < 0 || bc >= Inf) { cells = null; break; }
                cur = best;
                cells.Add(cur);
            }
            if (cells != null && cur == goal) path = Smooth(cells, from, goalPos);
        }
        sw.Stop();
        LastPlanMs = sw.Elapsed.TotalMilliseconds;
        LastStatus = "free=" + FreeCells + " start=" + (start % Width) + "," + (start / Width) + " blocked=" + blocked[start] +
                     " g=" + Meters(g[start]) + " rhs=" + Meters(rhs[start]) + " goal=" + (goal % Width) + "," + (goal / Width) +
                     " open=" + open.Count + " expanded=" + LastExpanded + " path=" + (path == null ? "null" : path.Count.ToString()) +
                     " ms=" + LastPlanMs.ToString("F2");
        return path;
    }

    // ---- D* Lite ----
    private static long Add(long a, long b) => (a >= Inf || b >= Inf) ? Inf : a + b;
    private string Meters(long c) => c >= Inf ? "inf" : (c * Cell / Straight).ToString("F2");

    private long H(int a, int b)
    {
        int dx = Mathf.Abs(a % Width - b % Width), dz = Mathf.Abs(a / Width - b / Width);
        return Straight * Mathf.Max(dx, dz) + (Diagonal - Straight) * Mathf.Min(dx, dz);
    }

    private long Cost(int a, int b)
    {
        if (blocked[a] || blocked[b]) return Inf;
        int ax = a % Width, az = a / Width, bx = b % Width, bz = b / Width;
        if (ax != bx && az != bz)
        {
            if (blocked[bx + az * Width] || blocked[ax + bz * Width]) return Inf;   // 모서리 스치기 금지
            return Diagonal;
        }
        return Straight;
    }

    private Key CalcKey(int s)
    {
        long m = Math.Min(g[s], rhs[s]);
        return new Key { k1 = m >= Inf ? Inf : m + H(start, s) + km, k2 = m, id = s };
    }

    private void Insert(int s, Key k) { keyOf[s] = k; inOpen[s] = true; open.Add(k); }
    private void Remove(int s) { if (inOpen[s]) { open.Remove(keyOf[s]); inOpen[s] = false; } }

    private void UpdateVertex(int u)
    {
        if (u != goal)
        {
            long best = Inf;
            int ux = u % Width, uz = u / Width;
            for (int k = 0; k < 8; k++)
            {
                int x = ux + DX[k], z = uz + DZ[k];
                if (x < 0 || z < 0 || x >= Width || z >= Height) continue;
                int s = x + z * Width;
                long c = Add(Cost(u, s), g[s]);
                if (c < best) best = c;
            }
            rhs[u] = best;
        }
        Remove(u);
        if (g[u] != rhs[u]) Insert(u, CalcKey(u));
    }

    private static bool Less(Key a, Key b) => a.k1 < b.k1 || (a.k1 == b.k1 && a.k2 < b.k2);

    private void ComputeShortestPath()
    {
        int guard = Width * Height * 20;
        while (open.Count > 0 && guard-- > 0)
        {
            Key top = open.Min;
            if (!(Less(top, CalcKey(start)) || rhs[start] != g[start])) break;
            int u = top.id;
            open.Remove(top); inOpen[u] = false;
            LastExpanded++;
            Key knew = CalcKey(u);
            if (Less(top, knew)) { Insert(u, knew); continue; }
            int ux = u % Width, uz = u / Width;
            if (g[u] > rhs[u])
            {
                g[u] = rhs[u];
            }
            else
            {
                g[u] = Inf;
                UpdateVertex(u);
            }
            for (int k = 0; k < 8; k++)
            {
                int x = ux + DX[k], z = uz + DZ[k];
                if (x < 0 || z < 0 || x >= Width || z >= Height) continue;
                UpdateVertex(x + z * Width);
            }
        }
    }

    // ---- 경로 줄이기 ----
    private bool LineFree(Vector3 a, Vector3 b)
    {
        float len = Vector3.Distance(a, b);
        int steps = Mathf.Max(1, Mathf.CeilToInt(len / (Cell * 0.5f)));
        for (int i = 0; i <= steps; i++)
        {
            Vector3 p = Vector3.Lerp(a, b, (float)i / steps);
            // 점을 둘러싼 칸이 모두 비어 있어야 한다 (칸 경계를 스치는 선을 막힌 것으로 본다)
            int x0 = Mathf.FloorToInt((p.x - origin.x) / Cell), z0 = Mathf.FloorToInt((p.z - origin.z) / Cell);
            for (int dz = 0; dz <= 1; dz++)
                for (int dx = 0; dx <= 1; dx++)
                {
                    int x = x0 + dx, z = z0 + dz;
                    if (x < 0 || z < 0 || x >= Width || z >= Height || blocked[x + z * Width]) return false;
                }
        }
        return true;
    }

    private List<Vector3> Smooth(List<int> cells, Vector3 from, Vector3 goalPos)
    {
        var pts = new List<Vector3>(cells.Count);
        foreach (int c in cells) pts.Add(Center(c));
        var outPath = new List<Vector3> { new Vector3(from.x, planeY, from.z) };
        int i = 0;
        while (i < pts.Count - 1)
        {
            int j = pts.Count - 1;
            while (j > i + 1 && !LineFree(pts[i], pts[j])) j--;
            outPath.Add(pts[j]);
            i = j;
        }
        Vector3 end = new Vector3(goalPos.x, planeY, goalPos.z);
        if (Vector3.Distance(outPath[outPath.Count - 1], end) > 0.01f) outPath.Add(end);
        return outPath;
    }
}
