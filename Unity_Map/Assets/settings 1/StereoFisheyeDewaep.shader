Shader "Go1/Stereo Fisheye Dewarp Overlay"
{
    Properties
    {
        _MainTex ("SBS Fisheye Texture", 2D) = "white" {}

        _ViewFovDeg ("View FOV Deg", Range(30, 140)) = 100
        _FishFovDeg ("Fisheye FOV Deg", Range(90, 220)) = 180

        _FishCenterX ("Fisheye Center X", Range(0, 1)) = 0.5
        _FishCenterY ("Fisheye Center Y", Range(0, 1)) = 0.5
        _FishRadius ("Fisheye Radius", Range(0.1, 0.8)) = 0.48

        _OutputAspect ("Output Aspect", Range(0.5, 2.5)) = 1.15

        _SwapEyes ("Swap Eyes", Float) = 0
        _FlipX ("Flip X", Float) = 0
        _FlipY ("Flip Y", Float) = 0
        _RotateDeg ("Rotate Deg", Range(-180, 180)) = 0
    }

    SubShader
    {
        Tags
        {
            "Queue"="Overlay"
            "RenderType"="Transparent"
            "IgnoreProjector"="True"
        }

        Cull Off
        Lighting Off
        ZWrite Off
        ZTest Always
        Blend SrcAlpha OneMinusSrcAlpha

        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag

            #pragma multi_compile_instancing
            #pragma multi_compile _ UNITY_SINGLE_PASS_STEREO

            #include "UnityCG.cginc"

            sampler2D _MainTex;

            float _ViewFovDeg;
            float _FishFovDeg;

            float _FishCenterX;
            float _FishCenterY;
            float _FishRadius;
            float _OutputAspect;

            float _SwapEyes;
            float _FlipX;
            float _FlipY;
            float _RotateDeg;

            struct appdata
            {
                float4 vertex : POSITION;
                float2 uv : TEXCOORD0;

                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                float2 uv : TEXCOORD0;

                UNITY_VERTEX_OUTPUT_STEREO
            };

            v2f vert(appdata v)
            {
                v2f o;

                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);

                o.vertex = UnityObjectToClipPos(v.vertex);
                o.uv = v.uv;

                return o;
            }

            fixed4 frag(v2f i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);

                float eye = unity_StereoEyeIndex;

                if (_SwapEyes > 0.5)
                {
                    eye = 1.0 - eye;
                }

                // Quad UV: 0~1 -> -1~1
                float2 p = i.uv * 2.0 - 1.0;

                if (_FlipX > 0.5)
                {
                    p.x = -p.x;
                }

                if (_FlipY > 0.5)
                {
                    p.y = -p.y;
                }

                // 화면 비율 보정
                p.x *= _OutputAspect;

                // 사용자가 보는 가상 시야각
                float viewFov = radians(_ViewFovDeg);
                float t = tan(viewFov * 0.5);

                // 평면 좌표를 3D 광선으로 변환
                float3 ray = normalize(float3(p.x * t, p.y * t, 1.0));

                // 전방 기준 각도
                float theta = acos(saturate(ray.z));

                // 어안 카메라 반시야각
                float fishHalfFov = radians(_FishFovDeg) * 0.5;

                // 어안 원 안에서의 반지름 비율
                float r = theta / fishHalfFov;

                if (r > 1.0)
                {
                    return fixed4(0, 0, 0, 1);
                }

                float2 dir = normalize(ray.xy + 1e-6);

                // 회전 보정
                float rot = radians(_RotateDeg);
                float cs = cos(rot);
                float sn = sin(rot);

                float2 rotatedDir;
                rotatedDir.x = dir.x * cs - dir.y * sn;
                rotatedDir.y = dir.x * sn + dir.y * cs;

                // 한쪽 어안 이미지 내부 UV
                float2 fishUV;
                fishUV.x = _FishCenterX + rotatedDir.x * r * _FishRadius;
                fishUV.y = _FishCenterY + rotatedDir.y * r * _FishRadius;

                // 어안 원 밖은 검정
                if (distance(fishUV, float2(_FishCenterX, _FishCenterY)) > _FishRadius)
                {
                    return fixed4(0, 0, 0, 1);
                }

                // 입력 영상이 [왼쪽 어안][오른쪽 어안] SBS 구조라고 가정
                float finalU;

                if (eye < 0.5)
                {
                    // 왼쪽 눈: 전체 이미지의 왼쪽 절반
                    finalU = fishUV.x * 0.5;
                }
                else
                {
                    // 오른쪽 눈: 전체 이미지의 오른쪽 절반
                    finalU = 0.5 + fishUV.x * 0.5;
                }

                float2 finalUV = float2(finalU, fishUV.y);

                fixed4 col = tex2D(_MainTex, finalUV);
                return col;
            }
            ENDCG
        }
    }

    FallBack Off
}