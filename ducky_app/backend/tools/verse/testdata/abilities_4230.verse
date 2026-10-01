using { /Fortnite.com/Abilities }
using { /Fortnite.com/Armory }
using { /Verse.org/SceneGraph }
using { /Verse.org/Simulation }

# 42.30: fort_template_ability is no longer parametric. Specialize it directly.
ducky_check_template_ability<public> := class(fort_template_ability):

# Target queries take an array of affiliations (Any is gone; Neutral is new).
DuckyCheckQuery<public>():fort_wedge_ability_target_query =
    fort_wedge_ability_target_query:
        Targets := array{fort_target_query_affiliation.Hostile, fort_target_query_affiliation.Neutral}
        Radius := 500.0
        CentralAngle := 90.0

DuckyCheckReticle<public>():fort_reticle_ability_target_query =
    fort_reticle_ability_target_query:
        Targets := array{fort_target_query_affiliation.Friendly}
        Range := 2000.0

# 42.30 weapon toggles: aim down sights in the air and while reloading.
DuckyCheckWeapon<public>(Weapon:fort_trace_weapon_component):void =
    Weapon.SetAllowAimDownSightsInAir(true)
    Weapon.SetAllowAimDownSightsDuringReload(false)

# The new held-item prefab is a concrete entity class.
DuckyCheckHeldItem<public>():entity = held_item_template{}
