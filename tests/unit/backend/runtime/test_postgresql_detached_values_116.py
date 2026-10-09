"""#116 semantic regression guards retained after abandoning the getter fast path.

These tests protect plugin-defined accessors, dynamic pointers and descriptors.
"""
from pyworkflow.object import Float, Pointer
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetMixin


def childrenOf(value):
    return PostgresqlRuntimeSetMixin._getDetachedScipionChildren(value)


def test_DynamicPointerInScalarIsStillVisible():
    scalar = Float(2.5)
    pointer = Pointer()
    scalar._pluginDynamicPointer = pointer
    children = childrenOf(scalar)
    assert len(children) == 1 and children[0] is pointer


def test_DataDescriptorShadowsInstanceValueAndMustBeHonored():
    class DescriptorFloat(Float):
        pass

    scalar = DescriptorFloat(1.0)
    pointer = Pointer()
    vars(scalar)['virtual'] = 'plain instance value'
    DescriptorFloat.virtual = property(lambda self: pointer)
    children = childrenOf(scalar)
    assert len(children) == 1 and children[0] is pointer


def test_CustomGetattributeMustRemainAuthoritative():
    pointer = Pointer()

    class CustomAccessFloat(Float):
        def __getattribute__(self, name):
            if name == 'virtual':
                return pointer
            return super().__getattribute__(name)

    scalar = CustomAccessFloat(1.0)
    vars(scalar)['virtual'] = 'plain instance value'
    children = childrenOf(scalar)
    assert len(children) == 1 and children[0] is pointer


def test_ClassLevelCustomGetterMustRemainAuthoritative():
    pointer = Pointer()

    class CustomGetterFloat(Float):
        def getAttributes(self):
            return [('virtual', pointer)]

    children = childrenOf(CustomGetterFloat(1.0))
    assert len(children) == 1 and children[0] is pointer


def test_InstanceLevelGetterOverrideMustRemainAuthoritative():
    scalar = Float(1.0)
    pointer = Pointer()
    scalar.getAttributes = lambda: [('virtual', pointer)]
    children = childrenOf(scalar)
    assert len(children) == 1 and children[0] is pointer


def test_InheritedDescriptorCollisionAlsoRequiresGetter():
    pointer = Pointer()

    class ParentFloat(Float):
        virtual = property(lambda self: pointer)

    class ChildFloat(ParentFloat):
        pass

    scalar = ChildFloat(1.0)
    vars(scalar)['virtual'] = 'plain instance value'
    children = childrenOf(scalar)
    assert len(children) == 1 and children[0] is pointer
