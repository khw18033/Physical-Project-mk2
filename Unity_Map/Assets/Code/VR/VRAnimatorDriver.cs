using UnityEngine;

public class VRAnimatorDriver : MonoBehaviour
{
    public Transform hmd;       
    public Animator animator;   

    [Header("Tuning")]
    public float speedSmooth = 12f;
    public float turnSmooth = 12f;

    float smSpeed, smTurn;
    Vector3 prevPos;
    float prevYaw;

    void Start()
    {
        if (hmd != null)
        {
            prevPos = hmd.position;
            prevYaw = hmd.eulerAngles.y;
        }

        if (animator == null) animator = GetComponent<Animator>();
    }

    void LateUpdate()
    {
        if (hmd == null || animator == null) return;

        float dt = Mathf.Max(Time.deltaTime, 0.0001f);

        Vector3 d = hmd.position - prevPos;
        d.y = 0f;
        float speed = d.magnitude / dt;

        float yaw = hmd.eulerAngles.y;
        float yawDelta = Mathf.DeltaAngle(prevYaw, yaw);
        float turn = Mathf.Clamp((yawDelta / dt) / 90f, -1f, 1f);

        smSpeed = Mathf.Lerp(smSpeed, speed, 1f - Mathf.Exp(-speedSmooth * dt));
        smTurn  = Mathf.Lerp(smTurn,  turn,  1f - Mathf.Exp(-turnSmooth * dt));

        animator.SetFloat("Speed", smSpeed);
        animator.SetFloat("Turn", smTurn);

        prevPos = hmd.position;
        prevYaw = yaw;
    }
}