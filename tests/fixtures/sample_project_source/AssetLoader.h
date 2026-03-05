#pragma once

#include "CoreMinimal.h"
#include "AssetLoader.generated.h"

DECLARE_LOG_CATEGORY_EXTERN(LogAssetLoader, Warning, All);

UCLASS()
class UAssetLoader : public UObject
{
    GENERATED_BODY()
public:
    void LoadWeapon();
};
