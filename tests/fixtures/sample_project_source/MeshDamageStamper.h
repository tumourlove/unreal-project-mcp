// Copyright YourProject

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "MeshDamageStamper.generated.h"

/**
 * Stamps damage decals onto mesh surfaces using runtime vertex painting.
 * Supports both static and skeletal meshes.
 */
UCLASS(ClassGroup=(Custom), meta=(BlueprintSpawnableComponent))
class YOURPROJECT_API UMeshDamageStamper : public UActorComponent
{
    GENERATED_BODY()

public:
    UMeshDamageStamper();

    /** Apply damage stamp at the given world location. */
    UFUNCTION(BlueprintCallable, Category = "Damage")
    void ApplyDamageStamp(const FVector& Location, float Radius, float Intensity);

    /** Get the total accumulated damage for this component. */
    UFUNCTION(BlueprintPure, Category = "Damage")
    float GetTotalDamage() const;

    UFUNCTION(BlueprintCallable, Category = "Damage")
    void ClearAllDamage();

protected:
    virtual void BeginPlay() override;
    virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Damage")
    float MaxDamageRadius = 100.0f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Damage")
    float DamageDecayRate = 0.1f;

private:
    UPROPERTY()
    TArray<FVector> DamagePoints;

    UPROPERTY()
    TArray<float> DamageIntensities;

    float TotalDamage = 0.0f;

    void UpdateDamageDecay(float DeltaTime);
    bool IsValidStampLocation(const FVector& Location) const;
};
