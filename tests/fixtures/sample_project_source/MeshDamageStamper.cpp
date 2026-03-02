#include "MeshDamageStamper.h"

UMeshDamageStamper::UMeshDamageStamper()
{
    PrimaryComponentTick.bCanEverTick = true;
}

void UMeshDamageStamper::BeginPlay()
{
    Super::BeginPlay();
}

void UMeshDamageStamper::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
    UpdateDamageDecay(DeltaTime);
}

void UMeshDamageStamper::ApplyDamageStamp(const FVector& Location, float Radius, float Intensity)
{
    if (!IsValidStampLocation(Location))
    {
        return;
    }

    DamagePoints.Add(Location);
    DamageIntensities.Add(FMath::Clamp(Intensity, 0.0f, 1.0f));
    TotalDamage += Intensity;
}

float UMeshDamageStamper::GetTotalDamage() const
{
    return TotalDamage;
}

void UMeshDamageStamper::ClearAllDamage()
{
    DamagePoints.Empty();
    DamageIntensities.Empty();
    TotalDamage = 0.0f;
}

void UMeshDamageStamper::UpdateDamageDecay(float DeltaTime)
{
    for (int32 i = DamageIntensities.Num() - 1; i >= 0; --i)
    {
        DamageIntensities[i] -= DamageDecayRate * DeltaTime;
        if (DamageIntensities[i] <= 0.0f)
        {
            DamagePoints.RemoveAt(i);
            DamageIntensities.RemoveAt(i);
        }
    }
}

bool UMeshDamageStamper::IsValidStampLocation(const FVector& Location) const
{
    return Location.Size() < MaxDamageRadius * 10.0f;
}
