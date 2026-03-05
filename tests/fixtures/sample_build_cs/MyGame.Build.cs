using UnrealBuildTool;

public class MyGame : ModuleRules
{
    public MyGame(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[] {
            "Core",
            "CoreUObject",
            "Engine",
            "InputCore"
        });

        PrivateDependencyModuleNames.AddRange(new string[] {
            "Slate",
            "SlateCore",
            "UMG"
        });

        PrivateDependencyModuleNames.Add("GameplayTags");

        DynamicallyLoadedModuleNames.Add("OnlineSubsystem");
    }
}
