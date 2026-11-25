using UnityEngine;

/// <summary>
/// 탐지 범위를 바닥에 색으로 표시하는 반투명 부채꼴/원판.
///   보라 = 360° 카메라가 장애물을 배치하는 범위 (Anchor360ObstacleReceiver)
///   초록 = Go1 정면 카메라가 물체를 표시하는 범위 (Go1FrontGuardReceiver)
/// 범위 밖 검출은 멀수록 위치·크기가 부정확해서 버린다.
/// 이름에 "floor" 를 넣어 기존 장애물 판정(겹침·시야 가림)에서 빠지게 한다. 콜라이더 없음.
/// </summary>
public static class RangeZone
{
    public static GameObject Make(string name, Color color)
    {
        var go = new GameObject(name + "_floor");
        go.AddComponent<MeshFilter>().mesh = new Mesh { name = name };
        var mr = go.AddComponent<MeshRenderer>();
        var sh = Shader.Find("Sprites/Default");
        if (sh == null) sh = Shader.Find("Unlit/Color");
        mr.material = new Material(sh) { color = color };
        mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        mr.receiveShadows = false;
        return go;
    }

    /// <summary>로컬 +z 를 가운데로 하는 부채꼴. halfAngleDeg=180 이면 원판. 위아래 양면.</summary>
    public static void Set(GameObject go, float radius, float halfAngleDeg)
    {
        if (go == null) return;
        var mesh = go.GetComponent<MeshFilter>().mesh;
        int seg = Mathf.Max(8, Mathf.CeilToInt(halfAngleDeg / 3f) * 2);
        var v = new Vector3[seg + 2];
        var tri = new int[seg * 6];
        v[0] = Vector3.zero;
        for (int i = 0; i <= seg; i++)
        {
            float a = Mathf.Deg2Rad * Mathf.Lerp(-halfAngleDeg, halfAngleDeg, i / (float)seg);
            v[i + 1] = new Vector3(Mathf.Sin(a) * radius, 0f, Mathf.Cos(a) * radius);
        }
        for (int i = 0; i < seg; i++)
        {
            tri[i * 6] = 0; tri[i * 6 + 1] = i + 1; tri[i * 6 + 2] = i + 2;      // 윗면
            tri[i * 6 + 3] = 0; tri[i * 6 + 4] = i + 2; tri[i * 6 + 5] = i + 1;  // 아랫면
        }
        mesh.Clear();
        mesh.vertices = v;
        mesh.triangles = tri;
        mesh.RecalculateBounds();
    }
}
