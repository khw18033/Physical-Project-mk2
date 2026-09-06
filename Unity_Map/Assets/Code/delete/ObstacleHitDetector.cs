using UnityEngine;

public class ObstacleHitDetector : MonoBehaviour
{
    public DynamicObstacleManager manager;

    void OnControllerColliderHit(ControllerColliderHit hit)
    {
        if (hit.gameObject.layer >= 7 && hit.gameObject.layer <= 12)
        {
            if (manager != null)
                manager.OnObstacleHit(gameObject);
        }
    }

    void OnCollisionEnter(Collision collision)
    {
        if (collision.gameObject.layer >= 7 && collision.gameObject.layer <= 12)
        {
            if (manager != null)
                manager.OnObstacleHit(gameObject);
        }
    }
}