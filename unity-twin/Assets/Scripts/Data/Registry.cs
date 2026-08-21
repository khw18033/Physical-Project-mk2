// Assets/Scripts/Data/Registry.cs
//
// 구성(레지스트리) 조회 — VZ-I-03 / REQ-304·305.
//
// **씬이 "의도적 미배포"를 그릴 수 있는 유일한 근거가 이것이다.** 미배포 대상은 값을
// 발행하지 않으므로 상태 메시지만으로는 씬에 영원히 나타나지 않고, '의도적 미배포'와
// '장애'를 구분할 수도 없다. robot-03 이 씬에 있으려면 이 조회가 성공해야 한다.
//
// 구성은 등록·배포·핸드오버 시점에만 바뀌므로 주기 폴링은 전부 낭비다.
// 최초 1회 조회하고, 변경 통지가 오면 갱신한다(통지 경로는 백엔드 확정 대기).
//
// **origin.position 은 이미 전역 좌표다.** 로컬→글로벌 변환은 백엔드 단독 책임이므로
// (BE-C-04 · DT-03) 여기서 하는 일은 받아서 배치하는 것뿐이다.

using System.Collections;
using System.Collections.Generic;
using Newtonsoft.Json;
using UnityEngine;
using UnityEngine.Networking;

namespace HybridDt.Twin.Data
{
    public sealed class RegistryVec3
    {
        [JsonProperty("x")] public double X;
        [JsonProperty("y")] public double Y;
        [JsonProperty("z")] public double Z;
    }

    public sealed class RegistryRotation
    {
        [JsonProperty("yaw_deg")] public double YawDeg;
        [JsonProperty("pitch_deg")] public double PitchDeg;
        [JsonProperty("roll_deg")] public double RollDeg;
    }

    /// <summary>REQ-302 — Node 원점의 **전역** 배치. 변환은 백엔드가 하고 뷰어는 놓기만 한다.</summary>
    public sealed class RegistryOrigin
    {
        [JsonProperty("position")] public RegistryVec3 Position;
        [JsonProperty("rotation")] public RegistryRotation Rotation;
        [JsonProperty("frame")] public string Frame;
    }

    public sealed class RegistryNode
    {
        [JsonProperty("id")] public string Id;
        [JsonProperty("zone")] public string Zone;
        [JsonProperty("display_name")] public string DisplayName;
        [JsonProperty("aliases")] public List<string> Aliases = new List<string>();
        [JsonProperty("origin")] public RegistryOrigin Origin;
    }

    public sealed class RegistryZone
    {
        [JsonProperty("id")] public string Id;
        [JsonProperty("display_name")] public string DisplayName;
        [JsonProperty("aliases")] public List<string> Aliases = new List<string>();
        [JsonProperty("nodes")] public List<string> Nodes = new List<string>();
    }

    public sealed class RegistryEntity
    {
        [JsonProperty("id")] public string Id;
        [JsonProperty("node")] public string Node;
        [JsonProperty("zone")] public string Zone;
        [JsonProperty("entity_type")] public string EntityType;
        [JsonProperty("display_name")] public string DisplayName;
        [JsonProperty("aliases")] public List<string> Aliases = new List<string>();
        [JsonProperty("channels")] public List<string> Channels = new List<string>();
        [JsonProperty("note")] public string Note;
    }

    public sealed class Registry
    {
        [JsonProperty("registry_version")] public string Version = "(미수신)";
        [JsonProperty("zones")] public List<RegistryZone> Zones = new List<RegistryZone>();
        [JsonProperty("nodes")] public List<RegistryNode> Nodes = new List<RegistryNode>();
        [JsonProperty("entities")] public List<RegistryEntity> Entities = new List<RegistryEntity>();

        public RegistryNode FindNode(string id)
        {
            if (id == null) return null;
            foreach (RegistryNode n in Nodes) if (n.Id == id) return n;
            return null;
        }
    }

    public sealed class RegistryFetchResult
    {
        public Registry Registry;
        /// <summary>실패 사유. null 이면 성공. **화면은 이 사실 자체를 표시한다.**</summary>
        public string Error;
    }

    public static class RegistryFetcher
    {
        /// <summary>
        /// REQ-204 — 레지스트리에 닿지 못해도 씬은 떠야 한다.
        /// 다른 파트의 진척에 가시화가 블로킹되지 않기 위한 요건이므로, 실패해도 빈 구성으로
        /// 진행하고 **"구성을 못 받았다"는 사실을 화면에 띄운다** — 값이 없는 것과 구성이
        /// 없는 것은 다르고, 씬이 비어 있는 이유가 둘 중 무엇인지 보여야 한다.
        /// </summary>
        public static IEnumerator Fetch(string httpBase, RegistryFetchResult result)
        {
            string url = httpBase.TrimEnd('/') + "/registry";

            using (UnityWebRequest req = UnityWebRequest.Get(url))
            {
                req.timeout = 5;
                yield return req.SendWebRequest();

#if UNITY_2020_2_OR_NEWER
                bool failed = req.result != UnityWebRequest.Result.Success;
#else
                bool failed = req.isNetworkError || req.isHttpError;
#endif
                if (failed)
                {
                    result.Registry = new Registry();
                    result.Error = "레지스트리 조회 실패 — " + url + " · " + req.error;
                    yield break;
                }

                try
                {
                    result.Registry = JsonConvert.DeserializeObject<Registry>(req.downloadHandler.text) ?? new Registry();
                    result.Error = null;
                }
                catch (System.Exception e)
                {
                    result.Registry = new Registry();
                    result.Error = "레지스트리 파싱 실패 — " + e.Message;
                }
            }

            if (result.Error != null) Debug.LogWarning("[VZ-I-03] " + result.Error);
        }
    }
}
