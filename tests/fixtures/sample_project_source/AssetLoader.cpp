#include "AssetLoader.h"

DEFINE_LOG_CATEGORY(LogAssetLoader);

void UAssetLoader::LoadWeapon()
{
    static ConstructorHelpers::FObjectFinder<UBlueprint> WeaponBP(
        TEXT("/Game/Blueprints/BP_Weapon"));

    FSoftObjectPath ShieldPath(TEXT("/Game/Blueprints/BP_Shield.BP_Shield_C"));

    UObject* Loaded = LoadObject<UStaticMesh>(
        nullptr, TEXT("/Game/Meshes/SM_Cube"));

    UE_LOG(LogAssetLoader, Warning, TEXT("Loading weapon blueprint"));
}
