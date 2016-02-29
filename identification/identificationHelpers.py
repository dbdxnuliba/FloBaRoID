import iDynTree

import time
class Timer(object):
    def __enter__(self):
        self.start = time.clock()
        return self

    def __exit__(self, *args):
        self.end = time.clock()
        self.interval = self.end - self.start

class IdentificationHelpers(object):
    def __init__(self, n_params):
        self.n_params = n_params

    def inertiaParams2RotationalInertiaRaw(self, params):
        #take values from inertia parameter vector and create iDynTree RotationalInertiaRaw matrix
        #expects six parameter vector

        inertia = iDynTree.RotationalInertiaRaw()
        #xx of inertia matrix w.r.t. link origin
        value = params[0]
        inertia.setVal(0, 0, value)
        #xy
        value = params[1]
        inertia.setVal(0, 1, value)
        inertia.setVal(1, 0, value)
        #xz
        value = params[2]
        inertia.setVal(0, 2, value)
        inertia.setVal(2, 0, value)
        #yy
        value = params[3]
        inertia.setVal(1, 1, value)
        #yz
        value = params[4]
        inertia.setVal(1, 2, value)
        inertia.setVal(2, 1, value)
        #zz
        value = params[5]
        inertia.setVal(2, 2, value)
        return inertia

    def paramsLink2Bary(self, params):
        ## convert params from iDynTree values (relative to link frame) to values usable in URDF (barycentric)
        ## (params are changed in place)

        #mass is mass
        #com in idyntree is represented as first moment of mass, so com * mass. URDF uses com
        #inertia in idyntree is represented w.r.t. frame origin. URDF uses w.r.t com

        for i in range(0, self.n_params):
            if (i % 10 == 0):   #for each joint
                link_mass = params[i]
                #com
                com_x = params[i+1]
                com_y = params[i+2]
                com_z = params[i+3]
                if link_mass != 0:
                    params[i+1] = com_x / link_mass  #x of first moment -> x of com
                    params[i+2] = com_y / link_mass  #y of first moment -> y of com
                    params[i+3] = com_z / link_mass  #z of first moment -> z of com
                p_com = iDynTree.PositionRaw(params[i+1], params[i+2], params[i+3])

                #inertias
                rot_inertia_origin = self.inertiaParams2RotationalInertiaRaw(params[i+4:i+10])
                s_inertia = iDynTree.SpatialInertiaRaw(link_mass, p_com, rot_inertia_origin)
                #s_inertia.fromRotationalInertiaWrtCenterOfMass(link_mass, p_com, rot_inertia)
                rot_inertia_com = s_inertia.getRotationalInertiaWrtCenterOfMass()
                params[i+4] = rot_inertia_com.getVal(0, 0)    #xx w.r.t. com
                params[i+5] = rot_inertia_com.getVal(0, 1)    #xy w.r.t. com
                params[i+6] = rot_inertia_com.getVal(0, 2)    #xz w.r.t. com
                params[i+7] = rot_inertia_com.getVal(1, 1)    #xx w.r.t. com
                params[i+8] = rot_inertia_com.getVal(1, 2)    #xy w.r.t. com
                params[i+9] = rot_inertia_com.getVal(2, 2)    #xz w.r.t. com

    def paramsBary2Link(self, params):
        return