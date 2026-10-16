using { /Fortnite.com/Abilities }
using { /Fortnite.com/Armory }
using { /Verse.org/SceneGraph }
using { /Verse.org/Simulation }

# 42.30: fort_template_ability is no longer parametric. Specialize it directly.
ducky_check_template_ability<public> := class(fort_template_ability):

# Target queries take an array of affiliations (Any is gone; Neutral is new).
# 42.40: CentralAngle (degrees) became Angle (radians).
DuckyCheckQuery<public>():fort_wedge_ability_target_query =
    fort_wedge_ability_target_query:
        Targets := array{fort_target_query_affiliation.Hostile, fort_target_query_affiliation.Neutral}
        Radius := 500.0
        Angle := 1.5708

# 42.40: self_ability_target_query became fort_self_ability_target_query.
DuckyCheckSelf<public>():fort_self_ability_target_query = fort_self_ability_target_query{}

# 42.40: attribute modifiers are in the digest.
DuckyCheckModifier<public>():fort_ability_attribute_modifier_point =
    fort_ability_attribute_modifier_point:
        AttributeModifiers := array{fort_attribute_modifier{Attribute := fort_ability_attribute.Speed, Modifier := fort_ability_attribute_modifier.Multiply, Value := 1.5}}
        ApplyToInstigator := true
        ApplyToTargets := false
        Duration := 3.0

# 42.40: open enum, so a case needs a default branch.
DuckyCheckSocket<public>(S:fort_ability_attach_socket):string =
    case (S):
        fort_ability_attach_socket.Root => "root"
        _ => "other"

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
