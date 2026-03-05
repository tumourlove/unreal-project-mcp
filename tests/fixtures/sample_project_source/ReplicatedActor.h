#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "ReplicatedActor.generated.h"

UCLASS()
class YOURPROJECT_API AReplicatedActor : public AActor
{
    GENERATED_BODY()

public:
    UFUNCTION(Server, Reliable)
    void ServerFireWeapon(FVector Direction);

    UFUNCTION(Client, Unreliable)
    void ClientPlayHitEffect(FVector Location);

    UFUNCTION(NetMulticast, Reliable)
    void MulticastOnDeath();

    UPROPERTY(Replicated)
    float Health;

    UPROPERTY(ReplicatedUsing=OnRep_Ammo)
    int32 Ammo;

    UFUNCTION()
    void OnRep_Ammo();
};
