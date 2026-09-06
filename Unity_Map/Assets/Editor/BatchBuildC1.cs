using UnityEditor;
using UnityEditor.Build.Reporting;

public static class BatchBuildC1
{
    public static void BuildC1Player()
    {
        var options = new BuildPlayerOptions
        {
            scenes = new[] { "Assets/XRI/lab.unity" },
            locationPathName = "D:/My project/Builds/C1Debug/C1Debug.exe",
            target = BuildTarget.StandaloneWindows64,
            options = BuildOptions.Development
        };

        BuildReport report = BuildPipeline.BuildPlayer(options);
        if (report.summary.result != BuildResult.Succeeded)
        {
            EditorApplication.Exit(1);
        }
        else
        {
            EditorApplication.Exit(0);
        }
    }
}
