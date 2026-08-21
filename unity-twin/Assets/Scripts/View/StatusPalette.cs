// Assets/Scripts/View/StatusPalette.cs
//
// 씬에서 상태를 **공간적으로** 구분하는 규칙 한 곳.
//
// ── 색만으로 구분하지 않는다
//
// 관제 화면에서 색약·저조도·프로젝터 투사는 흔한 조건이고, 그때 색만 다른 네 상태는
// 한 상태가 된다. 그래서 상태마다 **색 + 형태 + 자리**가 같이 바뀐다. 흑백으로 찍어도
// 넷이 구분돼야 한다는 것이 이 파일의 기준이다.
//
// ── 판단 불가를 "사라짐"으로 표현하지 않는다
//
// 없는 것과 모르는 것은 다르고, 관제에서 이 둘을 섞으면 위험하다. 판단 불가 대상은
// 자리에 남아 물음표 표식을 얹고, 미배포 대상도 흐리게라도 자리에 있어야
// "여기 있어야 할 게 안 왔다"가 보인다. 그래서 어떤 상태도 알파 0 이나 비활성으로
// 떨어지지 않는다.

using System.Collections.Generic;
using UnityEngine;
using HybridDt.Twin.Data;

namespace HybridDt.Twin.View
{
    public static class StatusPalette
    {
        // 상태 4종 (VZ-U-01).
        public static readonly Color Normal = new Color(0.28f, 0.78f, 0.44f);
        public static readonly Color Fault = new Color(0.90f, 0.29f, 0.27f);
        public static readonly Color NotDeployed = new Color(0.55f, 0.57f, 0.60f);
        public static readonly Color Unknown = new Color(0.95f, 0.72f, 0.20f);

        // 원천 종류 4종 (VZ-C-06).
        public static readonly Color OriginReal = new Color(0.93f, 0.95f, 0.98f);
        public static readonly Color OriginSimulated = new Color(0.25f, 0.80f, 0.90f);
        public static readonly Color OriginReplay = new Color(0.72f, 0.45f, 0.90f);
        public static readonly Color OriginUnknown = new Color(0.35f, 0.35f, 0.38f);

        public static readonly Color NodeOrigin = new Color(0.40f, 0.50f, 0.70f);
        public static readonly Color OutOfScope = new Color(0.45f, 0.45f, 0.50f);

        public static Color For(DisplayStatus status)
        {
            switch (status)
            {
                case DisplayStatus.Normal: return Normal;
                case DisplayStatus.Fault: return Fault;
                case DisplayStatus.NotDeployed: return NotDeployed;
                default: return Unknown;
            }
        }

        /// <summary>
        /// 상태별 **자리와 크기**. 색과 별개로 달라야 흑백에서도 구분된다.
        /// 미배포는 작고 낮게(자리는 지키되 존재감이 약하게), 판단 불가는 제 크기 그대로
        /// (모르는 것을 작게 그리면 "덜 중요한 것"으로 읽힌다).
        /// </summary>
        public static void ShapeFor(DisplayStatus status, out float scale, out float yOffset, out float alpha)
        {
            switch (status)
            {
                case DisplayStatus.Normal:
                    scale = 1.0f; yOffset = 0f; alpha = 1.0f; return;
                case DisplayStatus.Fault:
                    scale = 1.0f; yOffset = 0f; alpha = 1.0f; return;
                case DisplayStatus.NotDeployed:
                    scale = 0.6f; yOffset = -0.18f; alpha = 0.35f; return;
                default:
                    scale = 1.0f; yOffset = 0f; alpha = 0.75f; return;
            }
        }

        public static Color OriginColor(OriginKind kind)
        {
            switch (kind)
            {
                case OriginKind.Real: return OriginReal;
                case OriginKind.Simulated: return OriginSimulated;
                case OriginKind.Replay: return OriginReplay;
                default: return OriginUnknown;
            }
        }

        /// <summary>
        /// 원천 종류 표식의 **모양**. 색과 함께 바뀌므로 흑백에서도 실물과 시뮬레이션이 갈린다.
        /// 이번 범위의 검증(4-1)에서는 목 게이트웨이가 표기를 싣지 않으므로 전부 원기둥(=미상)이 뜬다.
        /// </summary>
        public static PrimitiveType OriginShape(OriginKind kind)
        {
            switch (kind)
            {
                case OriginKind.Real: return PrimitiveType.Cube;
                case OriginKind.Simulated: return PrimitiveType.Sphere;
                case OriginKind.Replay: return PrimitiveType.Capsule;
                default: return PrimitiveType.Cylinder; // 납작하게 눕혀 원반처럼 쓴다
            }
        }

        /// <summary>대상 종류별 기본 몸체. 프리팹이 없어도 씬이 성립하게 하는 대체물이다.</summary>
        public static PrimitiveType BodyFor(string entityType)
        {
            switch (entityType)
            {
                case "robot": return PrimitiveType.Capsule;
                case "sensor": return PrimitiveType.Cylinder;
                case "camera": return PrimitiveType.Cube;
                case "actuator": return PrimitiveType.Cube;
                case "edge_node": return PrimitiveType.Cube;
                default: return PrimitiveType.Sphere;
            }
        }

        // ── 머티리얼 ──────────────────────────────────────────────────────────

        private static readonly Dictionary<string, Material> Cache = new Dictionary<string, Material>();
        private static Shader _shader;

        /// <summary>
        /// 빌트인 렌더 파이프라인 기준. URP/HDRP 를 도입하지 않기로 했으므로 Standard 로 충분하다.
        /// 빌드에서 셰이더가 스트립되는 경우를 대비해 대체 사슬을 둔다(README 참조).
        /// </summary>
        private static Shader ResolveShader()
        {
            if (_shader != null) return _shader;
            _shader = Shader.Find("Standard")
                   ?? Shader.Find("Legacy Shaders/Diffuse")
                   ?? Shader.Find("Unlit/Color")
                   ?? Shader.Find("Sprites/Default");
            return _shader;
        }

        public static Material Get(Color color, float alpha)
        {
            string key = ColorUtility.ToHtmlStringRGB(color) + "_" + Mathf.RoundToInt(alpha * 100);
            Material cached;
            if (Cache.TryGetValue(key, out cached) && cached != null) return cached;

            Material m = new Material(ResolveShader());
            m.name = "twin_" + key;

            Color c = color;
            c.a = alpha;
            m.color = c;

            if (alpha < 0.999f && m.HasProperty("_Mode"))
            {
                // Standard 셰이더의 Fade 모드. 인스펙터에서 바꾸는 것과 같은 조작을 코드로 한다.
                m.SetFloat("_Mode", 2f);
                m.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
                m.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
                m.SetInt("_ZWrite", 0);
                m.DisableKeyword("_ALPHATEST_ON");
                m.EnableKeyword("_ALPHABLEND_ON");
                m.DisableKeyword("_ALPHAPREMULTIPLY_ON");
                m.renderQueue = 3000;
            }

            Cache[key] = m;
            return m;
        }
    }
}
