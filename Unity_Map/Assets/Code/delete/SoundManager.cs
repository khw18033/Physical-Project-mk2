using UnityEngine;
using UnityEngine.UI;

/*
===============================================================================
SoundManager.cs
-------------------------------------------------------------------------------
게임 전체 사운드 볼륨을 관리하는 UI 기반 사운드 매니저

[개요]
이 스크립트는 Master / BGM / UI / ETC 4가지 볼륨을
Unity UI Slider와 연결하여 실시간으로 조절할 수 있도록 한다.

각 슬라이더의 값(0~1)을 내부 변수에 반영하고,
추후 AudioSource 또는 AudioMixer에 연결할 수 있도록 설계된
기초 볼륨 제어 매니저이다.

-------------------------------------------------------------------------------
[구성 요소]

1) Master Volume
   - 전체 사운드에 공통으로 곱해질 기본 볼륨

2) BGM Volume
   - 배경음 전용 볼륨

3) UI Volume
   - 버튼 클릭음, 인터페이스 사운드 전용

4) ETC Volume
   - 효과음, 환경음 등 기타 사운드

-------------------------------------------------------------------------------
[동작 흐름]

Start()
 → InitSliders()
    → 각 Slider에 초기값 설정
    → onValueChanged 콜백 바인딩
       → 값 변경 시 내부 변수 갱신

-------------------------------------------------------------------------------
[현재 상태]

- 슬라이더 값은 내부 float 변수에만 반영됨
- 실제 AudioSource 또는 AudioMixer에는 아직 연결되지 않음

-------------------------------------------------------------------------------
[확장 방법]

1) AudioSource 직접 제어:
   audioSource.volume = masterVolume * bgmVolume;

2) AudioMixer 파라미터 제어 (권장):
   mixer.SetFloat("BGMVolume", Mathf.Log10(bgmVolume) * 20);

3) PlayerPrefs 저장 기능 추가 가능:
   PlayerPrefs.SetFloat("MasterVolume", masterVolume);

-------------------------------------------------------------------------------
[주의]

- 슬라이더가 Inspector에서 연결되지 않으면 동작하지 않음
- 현재는 값 저장 기능 없음 (씬 전환 시 초기화됨)

===============================================================================
*/
public class SoundManager : MonoBehaviour
{

    [Header("Volume Sliders")]
    public Slider masterVolumeSlider;
    public Slider bgmVolumeSlider;
    public Slider uiVolumeSlider;
    public Slider etcVolumeSlider;


    [Range(0f, 1f)] public float masterVolume = 1f;
    [Range(0f, 1f)] public float bgmVolume = 0.8f;
    [Range(0f, 1f)] public float uiVolume = 0.8f;
    [Range(0f, 1f)] public float etcVolume = 0.8f;

    void Start()
    {
        InitSliders();
    }

    void InitSliders()
    {
        BindSlider(masterVolumeSlider, masterVolume, OnMasterChanged);
        BindSlider(bgmVolumeSlider, bgmVolume, OnBgmChanged);
        BindSlider(uiVolumeSlider, uiVolume, OnUiChanged);
        BindSlider(etcVolumeSlider, etcVolume, OnEtcChanged);
    }

    void BindSlider(Slider slider, float defaultValue, UnityEngine.Events.UnityAction<float> callback)
    {
        if (slider == null) return;

        slider.minValue = 0f;
        slider.maxValue = 1f;
        slider.value = defaultValue;
        slider.onValueChanged.AddListener(callback);
    }


    void OnMasterChanged(float value)
    {
        masterVolume = value;
        Debug.Log($"[Sound] Master Volume: {value}");
    }

    void OnBgmChanged(float value)
    {
        bgmVolume = value;
        Debug.Log($"[Sound] BGM Volume: {value}");
    }

    void OnUiChanged(float value)
    {
        uiVolume = value;
        Debug.Log($"[Sound] UI Volume: {value}");
    }

    void OnEtcChanged(float value)
    {
        etcVolume = value;
        Debug.Log($"[Sound] ETC Volume: {value}");
    }
}
