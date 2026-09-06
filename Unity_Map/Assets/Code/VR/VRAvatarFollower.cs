using UnityEngine;

public class VRAvatarFollower : MonoBehaviour
{
    [Header("Targets")]
    public Transform xrOrigin;    
    public Transform hmd;        

    [Header("Follow Options")]
    public bool followPositionXZ = true;
    public bool followYawOnly = true;    
    public float fixedY = 0f;      

    [Header("Smoothing")]
    public float posLerp = 15f;
    public float rotLerp = 15f;

    void Reset()
    {
        fixedY = transform.position.y;
    }

    void LateUpdate()
    {
        if (xrOrigin == null) return;

        Vector3 targetPos = xrOrigin.position;
        if (followPositionXZ)
        {
            targetPos.y = fixedY;
        }

        transform.position = Vector3.Lerp(
            transform.position,
            targetPos,
            1f - Mathf.Exp(-posLerp * Time.deltaTime)
        );

        if (followYawOnly)
        {
            if (hmd == null) return;

            float yaw = hmd.eulerAngles.y;
            Quaternion targetRot = Quaternion.Euler(0f, yaw, 0f);

            transform.rotation = Quaternion.Slerp(
                transform.rotation,
                targetRot,
                1f - Mathf.Exp(-rotLerp * Time.deltaTime)
            );
        }
        else
        {
            transform.rotation = Quaternion.Slerp(
                transform.rotation,
                xrOrigin.rotation,
                1f - Mathf.Exp(-rotLerp * Time.deltaTime)
            );
        }
    }
}