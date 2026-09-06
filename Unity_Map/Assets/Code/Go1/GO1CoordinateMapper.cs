using UnityEngine;

/// <summary>
/// GO1/Unity/SDK 좌표계 변환을 한 곳에서만 관리하는 중앙 매퍼입니다.
///
/// 원칙:
/// 1) GO1LocalPathUdpSender는 Unity 경로를 SDK path-local 좌표로 바꿀 때만 이 클래스를 호출합니다.
/// 2) UnityTeleopAndMirror는 SDK state를 Unity 표시 좌표로 바꿀 때만 이 클래스를 호출합니다.
/// 3) 다른 스크립트에서는 swap/invert/yaw offset 값을 새로 만들지 않습니다.
/// </summary>
public class GO1CoordinateMapper : MonoBehaviour
{
    [Header("A. Unity Path -> SDK Path Local")]
    [Tooltip("Unity 경로 거리 -> 실제 GO1 경로 거리 전체 스케일. X/Z를 모두 같이 키우거나 줄입니다.")]
    public float pathDistanceScale = 1.0f;

    [Tooltip("SDK path-local X축만 추가로 키우거나 줄입니다. 현재 pathSwapXZ=true이면 Unity의 전진/후진(Z 이동)이 주로 이 값에 대응합니다.")]
    public float pathLocalXScale = 1.0f;

    [Tooltip("SDK path-local Z축만 추가로 키우거나 줄입니다. 현재 pathSwapXZ=true이면 Unity의 좌우(X 이동)가 주로 이 값에 대응합니다.")]
    public float pathLocalZScale = 1.0f;

    [Tooltip("Unity local x/z를 서로 바꿔서 SDK path-local x/z로 보냅니다.")]
    public bool pathSwapXZ = true;

    [Tooltip("SDK path-local x축 반전")]
    public bool pathInvertX = false;

    [Tooltip("SDK path-local z축 반전")]
    public bool pathInvertZ = true;

    [Tooltip("SDK path follower에서 yaw 부호가 반대로 적용될 때 켭니다.")]
    public bool pathInvertYawSign = true;

    [Tooltip("SDK로 보내는 waypoint yaw에 추가로 더할 보정 각도(deg)")]
    public float pathYawOffsetDeg = 0.0f;

    [Header("B. SDK State -> Unity Display")]
    [Tooltip("SDK state 위치 -> Unity 표시 거리 스케일")]
    public float statePosScale = 1.0f;

    [Tooltip("SDK state x/z를 Unity 표시 전에 서로 바꿉니다.")]
    public bool stateSwapXZ = false;

    [Tooltip("Unity에 표시되는 X 이동 방향을 반전합니다.")]
    public bool stateInvertX = false;

    [Tooltip("Unity에 표시되는 Z 이동 방향을 반전합니다.")]
    public bool stateInvertZ = false;

    [Tooltip("상태 표시용 x 스케일 미세 보정")]
    public float stateXScale = 1.0f;

    [Tooltip("상태 표시용 z 스케일 미세 보정")]
    public float stateZScale = 1.0f;

    [Tooltip("상태 표시용 x 오프셋")]
    public float stateXOffset = 0.0f;

    [Tooltip("상태 표시용 z 오프셋")]
    public float stateZOffset = 0.0f;

    // 이전 버전의 중복 좌우 반전 체크박스입니다.
    // 기존 Scene/Prefab 직렬화 값은 유지하되 Inspector에는 표시하지 않고,
    // 최초 검증 시 stateInvertZ 하나로 합칩니다.
    [SerializeField, HideInInspector]
    private bool mirrorSdkDisplayLateral = false;

    [SerializeField, HideInInspector]
    private bool legacyMirrorFlagMigrated = false;

    [Header("B-2. SDK State Position / Yaw Consistency")]
    [Tooltip("체크하면 SDK state 위치 벡터에 SDK yaw와 완전히 동일한 반사/회전 변환을 적용합니다.")]
    public bool enforceStatePositionYawConsistency = true;

    [Tooltip("엄격한 일관성 모드가 꺼져 있을 때만 Unity Yaw Fine Offset Deg를 위치에도 적용합니다.")]
    public bool applyUnityYawFineOffsetToStatePosition = true;

    [Tooltip("엄격한 일관성 모드가 꺼져 있을 때만 사용하는 추가 위치 회전값입니다.")]
    public float extraStatePositionRotationDeg = 0.0f;


    [Header("B-3. SDK State Delta -> Unity Body-Axis Reconstruction")]
    [Tooltip(
        "SDK의 연속 위치 변화량을 SDK yaw 기준 전진/좌우 성분으로 분해한 뒤, " +
        "Unity yaw 기준 전진/좌우 축으로 다시 조립합니다. " +
        "회전 후에도 전후와 좌우의 의미가 유지됩니다."
    )]
    public bool useBodyAxisStateDeltaMapping = true;

    [Tooltip(
        "몸체축 재구성 후 좌우만 반대일 때 체크합니다. " +
        "우선 해제 상태로 시험하십시오."
    )]
    public bool invertBodyAxisStateLateral = false;

    [Header("C. SDK Yaw -> Unity Yaw")]
    [Tooltip("SDK yaw를 Unity yaw로 표시할 때 부호 반전")]
    public bool invertSdkYawForUnity = true;

    [Tooltip("SDK yaw를 Unity yaw로 표시할 때 추가 offset(deg). 표시 전용 보정값입니다.")]
    public float sdkYawOffsetDeg = 0.0f;

    [Tooltip("기존 코드의 +180도 yaw 보정. 시작 각도가 뒤집히면 끄는 것을 권장합니다.")]
    public bool applyLegacyExtra180Yaw = false;

    [Tooltip("Unity yaw 표시 미세 보정(deg)")]
    public float unityYawFineOffsetDeg = 0.0f;

    [Header("D. Unity/VR/Keyboard -> SDK Command")]
    [Tooltip("Unity/VR/키보드에서 SDK로 보내는 전진·후진(vx) 명령 부호를 반전합니다.")]
    public bool commandInvertForward = false;

    [Tooltip("Unity/VR/키보드에서 SDK로 보내는 좌우(vy) 명령 부호를 반전합니다.")]
    public bool commandInvertLateral = false;

    [Tooltip("Unity/VR/키보드에서 SDK로 보내는 회전(wz) 명령 부호를 반전합니다.")]
    public bool commandInvertYaw = false;

    [Header("E. Final SDK Command -> Virtual Go1 Preview")]
    [Tooltip("가상 Go1 모델이 Unity에서 90도 돌아가 있어 W가 오른쪽, A가 앞으로 가는 경우 켭니다. 최종 명령을 (-vy, vx)로 변환합니다.")]
    public bool rotateVirtualCommandForModel90Deg = true;

    [Tooltip("현실 Go1에 보내는 최종 vx 명령을 가상 Go1에 적용할 때 사용하는 배율입니다. 방향 보정이 필요하면 -1도 사용할 수 있습니다.")]
    public float virtualCommandVxScale = 1.0f;

    [Tooltip("현실 Go1에 보내는 최종 vy 명령을 가상 Go1에 적용할 때 사용하는 배율입니다. 방향 보정이 필요하면 -1도 사용할 수 있습니다.")]
    public float virtualCommandVyScale = 1.0f;

    [Tooltip("현실 Go1에 보내는 최종 wz 명령을 가상 Go1에 적용할 때 사용하는 배율입니다.")]
    public float virtualCommandWzScale = 1.0f;

    [Header("F. Legacy Local Keyboard -> Unity")]
    [Tooltip("Go1WASDLegacyDrive의 로컬 WASD 이동에서 전진축과 좌우축을 서로 교환합니다.")]
    public bool legacyLocalSwapXZ = true;

    [Tooltip("Go1WASDLegacyDrive의 로컬 WASD 전진·후진 입력을 반전합니다.")]
    public bool legacyLocalInvertForward = true;

    [Tooltip("Go1WASDLegacyDrive의 로컬 WASD 좌우 입력을 반전합니다.")]
    public bool legacyLocalInvertStrafe = false;

    [Header("G. Visualization")]
    [Tooltip("C++에서 받은 waypoint 시각화에도 B의 SDK State -> Unity Display 매핑을 적용합니다.")]
    public bool applyMappingToWaypoints = true;

    [Header("Debug")]
    public bool logMapping = false;

    public Vector3 FinalSdkCommandToVirtual(float vx, float vy, float wz)
    {
        float virtualVx = vx;
        float virtualVy = vy;

        // 현재 가상 Go1 모델은 시각적 전진축이 Transform 기준 축과 90도 어긋나 있습니다.
        // 기존 증상:
        // W(vx+) -> 오른쪽, S(vx-) -> 왼쪽
        // A(vy+) -> 앞으로, D(vy-) -> 뒤로
        //
        // 아래 변환 후:
        // W -> 앞으로, S -> 뒤로, A -> 왼쪽, D -> 오른쪽
        if (rotateVirtualCommandForModel90Deg)
        {
            virtualVx = -vy;
            virtualVy = vx;
        }

        virtualVx *= virtualCommandVxScale;
        virtualVy *= virtualCommandVyScale;
        float virtualWz = wz * virtualCommandWzScale;

        return new Vector3(virtualVx, virtualVy, virtualWz);
    }

    public Vector2 UnityWorldToPathLocal2D(Vector3 worldPoint, Vector3 startWorldPos, Quaternion startWorldRot)
    {
        Vector3 delta = worldPoint - startWorldPos;
        Vector3 local = Quaternion.Inverse(startWorldRot) * delta;
        return UnityLocalXZToPathLocal2D(local.x, local.z);
    }

    public Vector2 UnityLocalXZToPathLocal2D(float unityLocalX, float unityLocalZ)
    {
        float x;
        float z;

        if (pathSwapXZ)
        {
            x = unityLocalZ;
            z = unityLocalX;
        }
        else
        {
            x = unityLocalX;
            z = unityLocalZ;
        }

        if (pathInvertX) x = -x;
        if (pathInvertZ) z = -z;

        // pathDistanceScale은 전체 경로 배율,
        // pathLocalXScale / pathLocalZScale은 SDK로 보내는 경로 좌표의 축별 배율입니다.
        // 현실 GO1의 전진 거리만 부족하면, 현재 설정(pathSwapXZ=true)에서는 보통 pathLocalXScale만 올립니다.
        x *= pathDistanceScale * pathLocalXScale;
        z *= pathDistanceScale * pathLocalZScale;

        return new Vector2(x, z);
    }

    public float PathDirectionToYawDeg(Vector2 pathDir)
    {
        float rawYawDeg = Mathf.Atan2(pathDir.x, pathDir.y) * Mathf.Rad2Deg;
        return PathRawYawToSendYawDeg(rawYawDeg);
    }

    public float PathRawYawToSendYawDeg(float rawYawDeg)
    {
        float yaw = pathInvertYawSign ? -rawYawDeg : rawYawDeg;
        yaw += pathYawOffsetDeg;
        return NormalizeDeg(yaw);
    }

    public Vector2 SdkRelativeXZToUnityDelta(float relX, float relZ)
    {
        float x;
        float z;

        if (enforceStatePositionYawConsistency)
        {
            Vector2 mapped = ApplySdkYawTransformToStateVector(relX, relZ);
            x = mapped.x;
            z = mapped.y;
        }
        else
        {
            x = relX;
            z = relZ;

            if (stateSwapXZ)
            {
                float tmp = x;
                x = z;
                z = tmp;
            }

            if (stateInvertX) x = -x;
            if (stateInvertZ) z = -z;

            float stateRotDeg = extraStatePositionRotationDeg;
            if (applyUnityYawFineOffsetToStatePosition)
                stateRotDeg += unityYawFineOffsetDeg;

            if (Mathf.Abs(stateRotDeg) > 0.0001f)
                RotateStateVector(ref x, ref z, stateRotDeg);
        }

        x *= statePosScale * stateXScale;
        z *= statePosScale * stateZScale;

        x += stateXOffset;
        z += stateZOffset;

        return new Vector2(x, z);
    }

    private Vector2 ApplySdkYawTransformToStateVector(float sdkX, float sdkZ)
    {
        float alphaDeg = GetSdkYawToUnityTotalOffsetDeg();
        float alphaRad = alphaDeg * Mathf.Deg2Rad;
        float cos = Mathf.Cos(alphaRad);
        float sin = Mathf.Sin(alphaRad);

        float unityX;
        float unityZ;

        if (invertSdkYawForUnity)
        {
            // theta' = -theta + alpha
            unityX = -sdkX * cos + sdkZ * sin;
            unityZ =  sdkX * sin + sdkZ * cos;
        }
        else
        {
            // theta' = theta + alpha
            unityX =  sdkX * cos + sdkZ * sin;
            unityZ = -sdkX * sin + sdkZ * cos;
        }

        return new Vector2(unityX, unityZ);
    }

    private float GetSdkYawToUnityTotalOffsetDeg()
    {
        float offset = sdkYawOffsetDeg;

        if (applyLegacyExtra180Yaw)
            offset += 180f;

        offset += unityYawFineOffsetDeg;
        return NormalizeDeg(offset);
    }

    private static void RotateStateVector(ref float x, ref float z, float angleDeg)
    {
        float rad = angleDeg * Mathf.Deg2Rad;
        float cos = Mathf.Cos(rad);
        float sin = Mathf.Sin(rad);

        float rx = x * cos - z * sin;
        float rz = x * sin + z * cos;

        x = rx;
        z = rz;
    }


    /// <summary>
    /// SDK 월드 위치 변화량을 몸체축 기준으로 분해한 뒤 Unity yaw 기준으로 재조립합니다.
    /// </summary>
    public Vector2 SdkStateWorldDeltaToUnityBodyDelta(
        float sdkDeltaX,
        float sdkDeltaZ,
        double sdkYawRad)
    {
        float sdkYaw = (float)sdkYawRad;

        Vector2 sdkForward = new Vector2(
            Mathf.Sin(sdkYaw),
            Mathf.Cos(sdkYaw)
        );

        Vector2 sdkRight = new Vector2(
            Mathf.Cos(sdkYaw),
            -Mathf.Sin(sdkYaw)
        );

        Vector2 sdkDelta = new Vector2(sdkDeltaX, sdkDeltaZ);

        float forwardAmount = -Vector2.Dot(sdkDelta, sdkForward);
        float lateralAmount = Vector2.Dot(sdkDelta, sdkRight);

        if (invertBodyAxisStateLateral)
            lateralAmount = -lateralAmount;

        float unityYawRad =
            SdkYawRadToUnityYawDeg(sdkYawRad) * Mathf.Deg2Rad;

        Vector2 unityForward = new Vector2(
            Mathf.Sin(unityYawRad),
            Mathf.Cos(unityYawRad)
        );

        Vector2 unityRight = new Vector2(
            Mathf.Cos(unityYawRad),
            -Mathf.Sin(unityYawRad)
        );

        Vector2 unityDelta =
            unityForward * forwardAmount +
            unityRight * lateralAmount;

        unityDelta.x *= statePosScale * stateXScale;
        unityDelta.y *= statePosScale * stateZScale;

        return unityDelta;
    }

    [ContextMenu("Validate Body-Axis State Delta Mapping")]
    public void ValidateBodyAxisStateDeltaMapping()
    {
        float[] angles = { 0f, 45f, 90f, 135f, 180f, -90f };
        float maxForwardError = 0f;
        float maxRightError = 0f;

        foreach (float sdkYawDeg in angles)
        {
            float sdkYawRad = sdkYawDeg * Mathf.Deg2Rad;

            Vector2 sdkForward = new Vector2(
                Mathf.Sin(sdkYawRad),
                Mathf.Cos(sdkYawRad)
            );

            Vector2 sdkRight = new Vector2(
                Mathf.Cos(sdkYawRad),
                -Mathf.Sin(sdkYawRad)
            );

            Vector2 mappedForward =
                SdkStateWorldDeltaToUnityBodyDelta(
                    sdkForward.x,
                    sdkForward.y,
                    sdkYawRad
                ).normalized;

            Vector2 mappedRight =
                SdkStateWorldDeltaToUnityBodyDelta(
                    sdkRight.x,
                    sdkRight.y,
                    sdkYawRad
                ).normalized;

            float unityYawRad =
                SdkYawRadToUnityYawDeg(sdkYawRad) * Mathf.Deg2Rad;

            Vector2 expectedForward = new Vector2(
                Mathf.Sin(unityYawRad),
                Mathf.Cos(unityYawRad)
            ).normalized;

            Vector2 expectedRight = new Vector2(
                Mathf.Cos(unityYawRad),
                -Mathf.Sin(unityYawRad)
            ).normalized;

            if (invertBodyAxisStateLateral)
                expectedRight = -expectedRight;

            float forwardError =
                Vector2.Distance(mappedForward, expectedForward);

            float rightError =
                Vector2.Distance(mappedRight, expectedRight);

            maxForwardError = Mathf.Max(maxForwardError, forwardError);
            maxRightError = Mathf.Max(maxRightError, rightError);
        }

        if (maxForwardError <= 0.0001f &&
            maxRightError <= 0.0001f)
        {
            Debug.Log(
                "[GO1 Body Axis] PASS: 모든 시험 각도에서 " +
                "전진/좌우 몸체축 변환이 일치합니다."
            );
        }
        else
        {
            Debug.LogError(
                $"[GO1 Body Axis] FAIL: " +
                $"forward={maxForwardError:E3}, " +
                $"right={maxRightError:E3}"
            );
        }
    }

    public float MapCommandVx(float vx)
    {
        return commandInvertForward ? -vx : vx;
    }

    public float MapCommandVy(float vy)
    {
        return commandInvertLateral ? -vy : vy;
    }

    public float MapCommandWz(float wz)
    {
        return commandInvertYaw ? -wz : wz;
    }

    public float SdkYawRadToUnityYawDeg(double sdkYawRad)
    {
        float yawDeg = (float)(sdkYawRad * Mathf.Rad2Deg);

        if (invertSdkYawForUnity)
            yawDeg = -yawDeg;

        yawDeg += sdkYawOffsetDeg;

        if (applyLegacyExtra180Yaw)
            yawDeg += 180f;

        yawDeg += unityYawFineOffsetDeg;

        return NormalizeDeg(yawDeg);
    }

    public float UnityYawDegToSdkYawRad(float unityYawDeg)
    {
        float sdkYawDeg = unityYawDeg;

        sdkYawDeg -= unityYawFineOffsetDeg;

        if (applyLegacyExtra180Yaw)
            sdkYawDeg -= 180f;

        sdkYawDeg -= sdkYawOffsetDeg;

        if (invertSdkYawForUnity)
            sdkYawDeg = -sdkYawDeg;

        sdkYawDeg = NormalizeDeg(sdkYawDeg);
        return sdkYawDeg * Mathf.Deg2Rad;
    }

    public void AlignSdkYawToUnityTarget(double sdkYawRad, float targetUnityYawDeg)
    {
        float sdkYawDeg = (float)(sdkYawRad * Mathf.Rad2Deg);
        float signedSdkYawDeg = invertSdkYawForUnity ? -sdkYawDeg : sdkYawDeg;
        float legacyExtra = applyLegacyExtra180Yaw ? 180f : 0f;

        sdkYawOffsetDeg = NormalizeDeg(
            targetUnityYawDeg - signedSdkYawDeg - legacyExtra - unityYawFineOffsetDeg
        );
    }

    public float GetTotalYawOffsetForSdkNotifyDeg()
    {
        return sdkYawOffsetDeg + unityYawFineOffsetDeg;
    }

    public static float NormalizeDeg(float deg)
    {
        while (deg > 180f) deg -= 360f;
        while (deg < -180f) deg += 360f;
        return deg;
    }

    [ContextMenu("Validate State Position / Yaw Consistency")]
    public void ValidateStatePositionYawConsistency()
    {
        float[] testAngles = { 0f, 45f, 90f, 135f, 180f, -90f };
        float maxError = 0f;

        foreach (float sdkYawDeg in testAngles)
        {
            float sdkYawRad = sdkYawDeg * Mathf.Deg2Rad;

            Vector2 sdkForward = new Vector2(
                Mathf.Sin(sdkYawRad),
                Mathf.Cos(sdkYawRad)
            );

            Vector2 mappedDirection =
                ApplySdkYawTransformToStateVector(sdkForward.x, sdkForward.y).normalized;

            float unityYawDeg = SdkYawRadToUnityYawDeg(sdkYawRad);
            float unityYawRad = unityYawDeg * Mathf.Deg2Rad;

            Vector2 unityHeading = new Vector2(
                Mathf.Sin(unityYawRad),
                Mathf.Cos(unityYawRad)
            ).normalized;

            float error = Vector2.Distance(mappedDirection, unityHeading);
            maxError = Mathf.Max(maxError, error);

            Debug.Log(
                $"[GO1 Mapper Consistency] sdkYaw={sdkYawDeg:F1}, " +
                $"positionDir={mappedDirection}, heading={unityHeading}, error={error:E3}"
            );
        }

        if (maxError <= 0.0001f)
            Debug.Log("[GO1 Mapper Consistency] PASS");
        else
            Debug.LogError($"[GO1 Mapper Consistency] FAIL maxError={maxError:E3}");
    }

    public string BuildSummary()
    {
        Vector2 unityForward = UnityLocalXZToPathLocal2D(0f, 1f);
        Vector2 unityRight = UnityLocalXZToPathLocal2D(1f, 0f);
        Vector2 unityBack = UnityLocalXZToPathLocal2D(0f, -1f);
        Vector2 unityLeft = UnityLocalXZToPathLocal2D(-1f, 0f);

        Vector2 sdkForwardShown = SdkRelativeXZToUnityDelta(0f, 1f);
        Vector2 sdkRightShown = SdkRelativeXZToUnityDelta(1f, 0f);

        return
            "[GO1CoordinateMapper]\n" +
            $"Unity local +Z -> SDK path local ({unityForward.x:F3}, {unityForward.y:F3})\n" +
            $"Unity local +X -> SDK path local ({unityRight.x:F3}, {unityRight.y:F3})\n" +
            $"Unity local -Z -> SDK path local ({unityBack.x:F3}, {unityBack.y:F3})\n" +
            $"Unity local -X -> SDK path local ({unityLeft.x:F3}, {unityLeft.y:F3})\n" +
            $"SDK state +Z -> Unity delta ({sdkForwardShown.x:F3}, {sdkForwardShown.y:F3})\n" +
            $"SDK state +X -> Unity delta ({sdkRightShown.x:F3}, {sdkRightShown.y:F3})\n" +
            $"pathSwapXZ={pathSwapXZ}, pathInvertX={pathInvertX}, pathInvertZ={pathInvertZ}, pathInvertYaw={pathInvertYawSign}\n" +
            $"pathDistanceScale={pathDistanceScale:F3}, pathLocalXScale={pathLocalXScale:F3}, pathLocalZScale={pathLocalZScale:F3}\n" +
            $"stateSwapXZ={stateSwapXZ}, stateInvertX={stateInvertX}, stateInvertZ={stateInvertZ}\n" +
            $"stateYawConsistency={enforceStatePositionYawConsistency}, statePosRotFromFine={applyUnityYawFineOffsetToStatePosition}, extraStateRot={extraStatePositionRotationDeg:F2}\n" +
            $"bodyAxisStateDelta={useBodyAxisStateDeltaMapping}, invertBodyLateral={invertBodyAxisStateLateral}\n" +
            $"commandInvertForward={commandInvertForward}, commandInvertLateral={commandInvertLateral}, commandInvertYaw={commandInvertYaw}\n" +
            $"virtualCommand90Deg={rotateVirtualCommandForModel90Deg}, virtualCommandScale=({virtualCommandVxScale:F3}, {virtualCommandVyScale:F3}, {virtualCommandWzScale:F3})\n" +
            $"legacySwapXZ={legacyLocalSwapXZ}, legacyInvertForward={legacyLocalInvertForward}, legacyInvertStrafe={legacyLocalInvertStrafe}\n" +
            $"invertSdkYaw={invertSdkYawForUnity}, yawOffset={sdkYawOffsetDeg:F2}, fineYaw={unityYawFineOffsetDeg:F2}, legacy180={applyLegacyExtra180Yaw}";
    }

    [ContextMenu("Print Mapping Summary")]
    public void PrintMappingSummary()
    {
        Debug.Log(BuildSummary());
    }

    private void MigrateLegacyMirrorFlag()
    {
        if (legacyMirrorFlagMigrated)
            return;

        // 이전에는 stateInvertZ와 mirrorSdkDisplayLateral이 각각 Z를 반전해
        // 두 체크박스를 동시에 켜면 서로 취소되었습니다.
        // XOR 결과를 stateInvertZ 하나에 보존합니다.
        if (mirrorSdkDisplayLateral)
            stateInvertZ = !stateInvertZ;

        mirrorSdkDisplayLateral = false;
        legacyMirrorFlagMigrated = true;
    }

    public void ValidateValues()
    {
        MigrateLegacyMirrorFlag();
        pathDistanceScale = Mathf.Max(0.0001f, pathDistanceScale);
        pathLocalXScale = Mathf.Max(0.0001f, pathLocalXScale);
        pathLocalZScale = Mathf.Max(0.0001f, pathLocalZScale);
        statePosScale = Mathf.Max(0.0001f, statePosScale);
        stateXScale = Mathf.Max(0.0001f, stateXScale);
        stateZScale = Mathf.Max(0.0001f, stateZScale);
        // 가상 미리보기는 현실 SDK 명령과 별도로 방향 보정이 필요할 수 있으므로
        // Vx/Vy Scale에 -1 같은 음수값도 허용합니다.
        // 예: 현실 A/D만 반대일 때 commandInvertLateral=true와
        //     virtualCommandVxScale=-1을 함께 사용하면 가상 방향은 유지됩니다.
        
    }

    private void Awake()
    {
        ValidateValues();
    }

    private void OnValidate()
    {
        ValidateValues();
    }
}