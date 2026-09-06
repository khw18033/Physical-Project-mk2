using UnityEngine;
using UnityEngine.AI;

public class GO1AutoNavigator : MonoBehaviour
{
    [Header("References")]
    public Transform startPoint;
    public Transform goalPoint;
    public NavMeshAgent agent;

    [Header("Control")]
    public KeyCode startSimulationKey = KeyCode.P;
    public KeyCode restoreControllersKey = KeyCode.O;
    public bool moveToStartBeforeRun = true;

    [Header("Scripts To Disable During Auto Run")]
    public MonoBehaviour[] scriptsToDisable;

    [Header("Optional Objects To Disable During Auto Run")]
    public GameObject[] objectsToDisable;

    [Header("Rotation Control")]
    public bool controlRotationManually = true;
    public float rotationSpeed = 8f;
    public float visualYawOffset = 90f;

    [Header("Arrival Settings")]
    public float arriveDistanceThreshold = 0.15f;
    public bool restoreControllersOnArrival = false;

    [Header("Path Visualization")]
    public LineRenderer pathLine;
    public float pathRefreshInterval = 0.2f;

    [Header("Local Path Sender")]
    public GO1LocalPathUdpSender localPathSender;
    public bool sendLocalPathOnStart = true;

    [Header("Debug")]
    public bool verboseLog = false;

    [Header("Status")]
    public bool isSimulating = false;
    public bool arrived = false;

    private float _lastPathRefreshTime;
    private bool[] _scriptPreviousStates;
    private bool[] _objectPreviousStates;
    private bool _controllersDisabled = false;

    void Start()
    {
        if (agent == null)
            agent = GetComponent<NavMeshAgent>();

        if (agent == null)
        {
            Debug.LogError("[GO1AutoNavigator] NavMeshAgent가 없습니다.");
            enabled = false;
            return;
        }

        agent.updateRotation = !controlRotationManually;
    }

    void Update()
    {
        if (Input.GetKeyDown(startSimulationKey))
        {
            if (!isSimulating)
                StartSimulation();
            else
                StopSimulation(false, true);
        }

        if (Input.GetKeyDown(restoreControllersKey))
            RestoreExternalControllersManually();

        if (!isSimulating) return;
        if (agent == null) return;

        if (!agent.isOnNavMesh)
        {
            Debug.LogWarning("[GO1AutoNavigator] agent가 NavMesh 위에서 벗어났습니다.");
            StopSimulation(false, true);
            return;
        }

        if (controlRotationManually)
            UpdateRotationToMovementDirection();

        UpdatePathLine();

        if (goalPoint == null) return;

        float directDistanceToGoal = Vector3.Distance(
            new Vector3(transform.position.x, 0f, transform.position.z),
            new Vector3(goalPoint.position.x, 0f, goalPoint.position.z)
        );

        if (!agent.pathPending)
        {
            if (directDistanceToGoal <= arriveDistanceThreshold)
            {
                StopSimulation(true, restoreControllersOnArrival);
                return;
            }

            if (agent.remainingDistance <= Mathf.Max(agent.stoppingDistance, arriveDistanceThreshold))
            {
                if (!agent.hasPath || agent.velocity.sqrMagnitude < 0.0001f)
                {
                    StopSimulation(true, restoreControllersOnArrival);
                    return;
                }
            }
        }

        if (verboseLog)
        {
            Debug.Log(
                $"[GO1AutoNavigator] moving | pos={transform.position} | " +
                $"remaining={agent.remainingDistance:F3} | hasPath={agent.hasPath}"
            );
        }
    }

    public void StartSimulation()
    {
        if (startPoint == null || goalPoint == null)
        {
            Debug.LogWarning("[GO1AutoNavigator] startPoint 또는 goalPoint가 없습니다.");
            return;
        }

        if (agent == null)
        {
            Debug.LogWarning("[GO1AutoNavigator] agent가 없습니다.");
            return;
        }

        agent.updateRotation = !controlRotationManually;

        DisableExternalControllers();

        if (moveToStartBeforeRun)
        {
            bool warpOk = WarpToStart();
            if (!warpOk)
            {
                Debug.LogWarning("[GO1AutoNavigator] 시작 위치 이동 실패");
                EnableExternalControllers();
                return;
            }
        }

        if (!agent.isOnNavMesh)
        {
            Debug.LogWarning("[GO1AutoNavigator] agent가 NavMesh 위에 없습니다.");
            EnableExternalControllers();
            return;
        }

        bool pathOk = SetDestination(goalPoint.position);
        if (!pathOk)
        {
            Debug.LogWarning("[GO1AutoNavigator] 유효한 경로를 찾지 못했습니다.");
            EnableExternalControllers();
            return;
        }

        if (sendLocalPathOnStart && localPathSender != null)
        {
            localPathSender.CaptureStartPose(transform.position, transform.rotation);
            localPathSender.SendPathFromCorners(agent.path.corners);
        }

        GO1Agent mlAgent = GetComponent<GO1Agent>();
        if (mlAgent != null)
            mlAgent.OnNavigatorStarted();

        arrived = false;
        isSimulating = true;
        Debug.Log("[GO1AutoNavigator] 시뮬레이션 시작");
    }

    public void StopSimulation(bool success)
    {
        StopSimulation(success, true);
    }

    public void StopSimulation(bool success, bool restoreControllers)
    {
        isSimulating = false;
        arrived = success;

        if (agent != null && agent.isOnNavMesh)
        {
            agent.ResetPath();
            agent.velocity = Vector3.zero;
        }

        ClearPathLine();

        if (restoreControllers)
            EnableExternalControllers();
        else
            Debug.Log("[GO1AutoNavigator] 외부 제어 스크립트 비활성화 유지");

        GO1Agent mlAgent = GetComponent<GO1Agent>();
        if (mlAgent != null)
        {
            mlAgent.enabled = true;
            mlAgent.OnNavigatorArrived();
        }

        if (success)
            Debug.Log("[GO1AutoNavigator] 목표 지점 도착");
        else
            Debug.Log("[GO1AutoNavigator] 시뮬레이션 중지");
    }

    public void RestoreExternalControllersManually()
    {
        if (_controllersDisabled)
        {
            EnableExternalControllers();
            Debug.Log("[GO1AutoNavigator] 외부 제어 수동 복구");
        }
        else
        {
            Debug.Log("[GO1AutoNavigator] 이미 활성화 상태입니다.");
        }
    }

    public bool WarpToStart()
    {
        if (startPoint == null) return false;

        NavMeshHit hit;
        if (NavMesh.SamplePosition(startPoint.position, out hit, 5.0f, NavMesh.AllAreas))
        {
            bool warpResult = agent.Warp(hit.position);
            if (verboseLog)
                Debug.Log($"[GO1AutoNavigator] 워프 결과={warpResult}, pos={hit.position}");
            return warpResult;
        }

        Debug.LogWarning("[GO1AutoNavigator] 시작 지점이 NavMesh 위에 없습니다.");
        return false;
    }

    public bool SetDestination(Vector3 targetPosition)
    {
        if (!agent.isOnNavMesh) return false;

        NavMeshHit hit;
        if (!NavMesh.SamplePosition(targetPosition, out hit, 5.0f, NavMesh.AllAreas))
        {
            Debug.LogWarning("[GO1AutoNavigator] 목표가 NavMesh 위에 없습니다.");
            return false;
        }

        NavMeshPath path = new NavMeshPath();
        bool calcOk = agent.CalculatePath(hit.position, path);

        if (calcOk && path.status == NavMeshPathStatus.PathComplete)
        {
            agent.SetPath(path);
            return true;
        }

        return false;
    }

    private void UpdateRotationToMovementDirection()
    {
        if (agent == null) return;

        Vector3 dir = agent.desiredVelocity;
        if (dir.sqrMagnitude < 0.0001f) dir = agent.velocity;
        dir.y = 0f;
        if (dir.sqrMagnitude < 0.0001f) return;

        Quaternion targetRot = Quaternion.LookRotation(dir.normalized);
        targetRot *= Quaternion.Euler(0f, visualYawOffset, 0f);

        transform.rotation = Quaternion.Slerp(
            transform.rotation, targetRot, Time.deltaTime * rotationSpeed
        );
    }

    public void DisableExternalControllers()
    {
        if (_controllersDisabled) return;

        if (scriptsToDisable != null)
        {
            _scriptPreviousStates = new bool[scriptsToDisable.Length];
            for (int i = 0; i < scriptsToDisable.Length; i++)
            {
                if (scriptsToDisable[i] == null) continue;
                _scriptPreviousStates[i] = scriptsToDisable[i].enabled;
                scriptsToDisable[i].enabled = false;
                Debug.Log($"[GO1AutoNavigator] 비활성화: {scriptsToDisable[i].GetType().Name}");
            }
        }

        if (objectsToDisable != null)
        {
            _objectPreviousStates = new bool[objectsToDisable.Length];
            for (int i = 0; i < objectsToDisable.Length; i++)
            {
                if (objectsToDisable[i] == null) continue;
                _objectPreviousStates[i] = objectsToDisable[i].activeSelf;
                objectsToDisable[i].SetActive(false);
                Debug.Log($"[GO1AutoNavigator] 오브젝트 비활성화: {objectsToDisable[i].name}");
            }
        }

        _controllersDisabled = true;
    }

    public void EnableExternalControllers()
    {
        if (!_controllersDisabled) return;

        if (scriptsToDisable != null && _scriptPreviousStates != null)
        {
            for (int i = 0; i < scriptsToDisable.Length; i++)
            {
                if (scriptsToDisable[i] == null) continue;
                bool prev = (i < _scriptPreviousStates.Length) ? _scriptPreviousStates[i] : true;
                scriptsToDisable[i].enabled = prev;
                Debug.Log($"[GO1AutoNavigator] 복구: {scriptsToDisable[i].GetType().Name} -> {prev}");
            }
        }

        if (objectsToDisable != null && _objectPreviousStates != null)
        {
            for (int i = 0; i < objectsToDisable.Length; i++)
            {
                if (objectsToDisable[i] == null) continue;
                bool prev = (i < _objectPreviousStates.Length) ? _objectPreviousStates[i] : true;
                objectsToDisable[i].SetActive(prev);
                Debug.Log($"[GO1AutoNavigator] 오브젝트 복구: {objectsToDisable[i].name} -> {prev}");
            }
        }

        _controllersDisabled = false;
    }

    private void UpdatePathLine()
    {
        if (pathLine == null) return;
        if (Time.time - _lastPathRefreshTime < pathRefreshInterval) return;

        _lastPathRefreshTime = Time.time;

        NavMeshPath path = agent.path;
        if (path == null || path.corners == null || path.corners.Length == 0)
        {
            pathLine.positionCount = 0;
            return;
        }

        pathLine.positionCount = path.corners.Length;
        for (int i = 0; i < path.corners.Length; i++)
            pathLine.SetPosition(i, path.corners[i]);
    }

    private void ClearPathLine()
    {
        if (pathLine != null)
            pathLine.positionCount = 0;
    }

    [ContextMenu("Send Current Path Via LocalPathSender")]
    public void SendCurrentPathViaLocalPathSender()
    {
        if (localPathSender == null) return;
        if (agent == null || agent.path == null || agent.path.corners == null) return;

        localPathSender.CaptureStartPose(transform.position, transform.rotation);
        localPathSender.SendPathFromCorners(agent.path.corners);
    }

    private void OnDisable()
    {
        if (_controllersDisabled)
            EnableExternalControllers();
    }

    private void OnDestroy()
    {
        if (_controllersDisabled)
            EnableExternalControllers();
    }
}