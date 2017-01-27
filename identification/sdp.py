from __future__ import division
from __future__ import print_function
from __future__ import absolute_import
from builtins import zip
from builtins import range

import sys
import numpy as np
import numpy.linalg as la
import scipy
import scipy.linalg as sla

import sympy
from sympy import Symbol, solve, Matrix, BlockMatrix, ZeroMatrix, Identity, zeros, eye
from distutils.version import LooseVersion
is_old_sympy = LooseVersion(sympy.__version__) < LooseVersion('0.7.5')
if is_old_sympy:
    print("Old sympy version found (< 0.7.5)! Please update.")

from identification import sdp_helpers
from identification.sdp_helpers import LMI_PSD, LMI_PD
from identification import helpers

from IPython import embed

class SDP(object):
    def initSDP_LMIs(self, idf, remove_nonid=True):
        ''' initialize LMI matrices to set physical consistency constraints for SDP solver
            based on Sousa, 2014 and corresponding code (https://github.com/cdsousa/IROS2013-Feas-Ident-WAM7)
        '''

        with helpers.Timer() as t:
            if idf.opt['verbose']:
                print("Initializing LMIs...")

            def skew(v):
                return Matrix([ [     0, -v[2],  v[1] ],
                                [  v[2],     0, -v[0] ],
                                [ -v[1],  v[0],   0 ] ])
            I = Identity
            S = skew

            # create LMI matrices (symbols) for each link
            # so that mass is positive, inertia matrix is positive definite
            # (each matrix block is constrained to be >0 or >=0)
            D_inertia_blocks = []

            if idf.opt['floatingBase'] is 0 and idf.opt['deleteFixedBase']:
                #don't include equations for 0'th link (as it's fixed)
                self.delete_cols = [0,1,2,3,4,5,6,7,8,9]
                if set(self.delete_cols).issubset(idf.model.non_id):
                    start_link = 1
                else:
                    start_link = 0
                    self.delete_cols = []
            else:
                start_link = 0
                self.delete_cols = []

            for i in range(start_link, idf.model.N_LINKS):
                m = idf.model.mass_syms[i]
                l = Matrix([ idf.model.param_syms[i*10+1],
                             idf.model.param_syms[i*10+2],
                             idf.model.param_syms[i*10+3] ] )
                L = Matrix([ [idf.model.param_syms[i*10+4+0],
                              idf.model.param_syms[i*10+4+1],
                              idf.model.param_syms[i*10+4+2]],
                             [idf.model.param_syms[i*10+4+1],
                              idf.model.param_syms[i*10+4+3],
                              idf.model.param_syms[i*10+4+4]],
                             [idf.model.param_syms[i*10+4+2],
                              idf.model.param_syms[i*10+4+4],
                              idf.model.param_syms[i*10+4+5]]
                           ])

                '''
                if remove_nonid and i == 1:  #test for kuka non-id'able params
                        L_star = Matrix([[idf.model.param_syms[i*10+4+5]]])
                        #s_star = Matrix([[l[0], l[1]]])
                        #Di = BlockMatrix([[L_star, s_star],
                        #                 [s_star.T, I(2)*idf.model.xStdModel[10]]])

                        Di = BlockMatrix([[L_star]])
                        D_inertia_blocks.append(Di.as_mutable())
                        self.delete_cols.extend([10,11,12,13,14,15,16,17,18])
                        #self.delete_cols.extend([10,13,14,15,16,17,18])
                        start_link = 2
                        #elif i == 2:
                        #    Di = BlockMatrix([[L,    S(l).T],
                        #                      [S(l), I(3)*idf.model.xStdModel[20]]])
                        #    self.delete_cols.append(20)
                        #    D_inertia_blocks.append(Di.as_mutable())
                else:
                '''
                Di = BlockMatrix([[L,    S(l).T],
                                  [S(l), I(3)*m]])
                D_inertia_blocks.append(Di.as_mutable())

            D_other_blocks = []

            params_to_skip = []

            # collect constraint flags for display
            self.constr_per_param = {}
            for i in range(idf.model.num_params):
                self.constr_per_param[i] = []

            '''
            # constraining like this often results in no solutions
            if idf.opt['limitNonIdentifiable']:
                for p in idf.model.non_id:
                    if p not in self.delete_cols: #and p%10>3:
                        #params_to_skip.append(p)
                        tol = 2
                        ub = Matrix([idf.model.xStdModel[p]+tol - idf.model.param_syms[i]])
                        lb = Matrix([idf.model.xStdModel[p]-tol + idf.model.param_syms[i]])
                        D_other_blocks.append(ub)
                        D_other_blocks.append(lb)
                        self.constr_per_param[p].append('prox')
            '''

            # look at condition numbers per link
            linkConds = idf.model.getSubregressorsConditionNumbers()
            robotmass_apriori = 0
            for i in range(0, idf.model.N_LINKS):
                robotmass_apriori+= idf.model.xStdModel[i*10]  #count a priori link masses

                #for links that have too high condition number, don't change params
                if idf.opt['noChange'] and linkConds[i] > idf.opt['noChangeThresh']:
                    print(Fore.YELLOW + 'skipping identification of link {} ({})!'.format(i, idf.model.linkNames[i]) + Fore.RESET)
                    # don't change mass
                    params_to_skip.append(i*10)

                    # don't change COM
                    params_to_skip.append(i*10+1)
                    params_to_skip.append(i*10+2)
                    params_to_skip.append(i*10+3)

                    # don't change inertia
                    params_to_skip.append(i*10+4)
                    params_to_skip.append(i*10+5)
                    params_to_skip.append(i*10+6)
                    params_to_skip.append(i*10+7)
                    params_to_skip.append(i*10+8)
                    params_to_skip.append(i*10+9)

            # manually fixed params
            for p in idf.opt['dontChangeParams']:
                params_to_skip.append(p)

            # create the don't-change constraints
            for p in set(params_to_skip):
                if p not in idf.opt['dontConstrain']:
                    D_other_blocks.append(Matrix([idf.model.xStdModel[p] - idf.model.param_syms[p]]))
                    D_other_blocks.append(Matrix([idf.model.param_syms[p] - idf.model.xStdModel[p]]))
                    self.constr_per_param[p].append('cad')

            # constrain overall mass within bounds
            if idf.opt['limitOverallMass']:
                #use given overall mass else use overall mass from CAD
                if idf.opt['limitMassVal']:
                    robotmaxmass = idf.opt['limitMassVal'] - sum(idf.model.xStdModel[0:start_link*10:10])
                    robotmaxmass_ub = robotmaxmass * 1.01
                    robotmaxmass_lb = robotmaxmass * 0.99
                else:
                    robotmaxmass = robotmass_apriori
                    # constrain with a bit of space around
                    robotmaxmass_ub = robotmaxmass * 1.3
                    robotmaxmass_lb = robotmaxmass * 0.7

                D_other_blocks.append(Matrix([robotmaxmass_ub - sum(idf.model.mass_syms[start_link:])])) #maximum mass
                D_other_blocks.append(Matrix([sum(idf.model.mass_syms[start_link:]) - robotmaxmass_lb])) #minimum mass

            # constrain for each link separately
            if idf.opt['limitMassToApriori']:
                # constrain each mass to env of a priori value
                for i in range(start_link, idf.model.N_LINKS):
                    if not (idf.opt['noChange'] and linkConds[i] > idf.opt['noChangeThresh']):
                        p = i*10
                        if p not in idf.opt['dontConstrain']:
                            ub = Matrix([idf.model.xStdModel[p]*(1+idf.opt['limitMassAprioriBoundary']) -
                                        idf.model.mass_syms[i]])
                            lb = Matrix([idf.model.mass_syms[i] -
                                         idf.model.xStdModel[p]*(1-idf.opt['limitMassAprioriBoundary'])])
                            D_other_blocks.append(ub)
                            D_other_blocks.append(lb)
                            self.constr_per_param[p].append('mA')

            if idf.opt['restrictCOMtoHull']:
                link_cuboid_hulls = np.zeros((idf.model.N_LINKS, 3, 2))
                for i in range(start_link, idf.model.N_LINKS):
                    if not (idf.opt['noChange'] and linkConds[i] > idf.opt['noChangeThresh']):
                        link_cuboid_hulls[i] = np.array(
                            idf.urdfHelpers.getBoundingBox(
                                input_urdf = idf.model.urdf_file,
                                old_com = idf.model.xStdModel[i*10+1:i*10+4],
                                link_nr = i
                            )
                        )
                        #print link_cuboid_hulls[i]*idf.model.xStdModel[i*10]
                        l = Matrix( idf.model.param_syms[i*10+1:i*10+4])
                        m = idf.model.mass_syms[i]

                        link_cuboid_hull = link_cuboid_hulls[i]
                        for j in range(3):
                            p = i*10+1+j
                            if p not in self.delete_cols and p not in idf.opt['dontConstrain']:
                                ub = Matrix( [[  l[j] - m*link_cuboid_hull[j][0] ]] )
                                lb = Matrix( [[ -l[j] + m*link_cuboid_hull[j][1] ]] )
                                D_other_blocks.append( ub )
                                D_other_blocks.append( lb )
                                self.constr_per_param[p].append('hull')

            # symmetry constraints
            if idf.opt['useSymmetryConstraints'] and idf.opt['symmetryConstraints']:
                for (a, b, sign) in idf.opt['symmetryConstraints']:
                    stol = idf.opt['symmetryTolerance']
                    D_other_blocks.append(Matrix([idf.model.param_syms[a] - sign*idf.model.param_syms[b]*(1.0-stol)]))
                    D_other_blocks.append(Matrix([sign*idf.model.param_syms[b] - idf.model.param_syms[a]*(1.0-stol)]))
                    self.constr_per_param[a].append('sym')
                    self.constr_per_param[b].append('sym')

            if idf.opt['identifyFriction']:
                # friction constraints
                # (only makes sense when no offsets on torque measurements, otherwise can be
                # negative)
                for i in range(idf.model.N_DOFS):
                    #Fc > 0
                    p = idf.model.num_inertial_params+i
                    D_other_blocks.append( Matrix([idf.model.param_syms[p]]) )
                    #Fv > 0
                    D_other_blocks.append( Matrix([idf.model.param_syms[p+idf.model.N_DOFS]]) )
                    D_other_blocks.append( Matrix([idf.model.param_syms[p+idf.model.N_DOFS*2]]) )
                    self.constr_per_param[p].append('>0')
                    self.constr_per_param[p+idf.model.N_DOFS].append('>0')
                    self.constr_per_param[p+idf.model.N_DOFS*2].append('>0')

            self.D_blocks = D_inertia_blocks + D_other_blocks

            #self.LMIs = list(map(LMI_PD, self.D_blocks))
            epsilon_safemargin = 1e-6
            self.LMIs_marg = list([LMI_PSD(lm - epsilon_safemargin*eye(lm.shape[0])) for lm in self.D_blocks])

        if idf.opt['showTiming']:
            print("Initializing LMIs took %.03f sec." % (t.interval))


    def identifyFeasibleStandardParameters(self, idf):
        ''' use SDP optimization to solve constrained OLS to find globally optimal physically
            feasible std parameters (not necessarily unique). Based on code from Sousa, 2014
        '''
        with helpers.Timer() as t:
            #if idf.opt['useAPriori']:
            #    print("Please disable using a priori parameters when using constrained optimization.")
            #    sys.exit(1)

            if idf.opt['verbose']:
                print("Preparing SDP...")

            I = Identity
            delta = Matrix(idf.model.param_syms)

            #ignore some cols that are non-identifiable
            for c in reversed(self.delete_cols):
                delta.row_del(c)

            YBase = idf.model.YBase
            tau = idf.model.torques_stack   #always absolute torque values

            Q, R = la.qr(YBase)
            Q1 = Q[:, 0:idf.model.num_base_params]
            #Q2 = Q[:, idf.model.num_base_params:]
            rho1 = Q1.T.dot(tau)
            R1 = np.matrix(R[:idf.model.num_base_params, :idf.model.num_base_params])

            # get projection matrix so that xBase = K*xStd
            if idf.opt['useBasisProjection']:
                K = Matrix(idf.model.Binv)
            else:
                #Sousa: K = Pb.T + Kd * Pd.T (Kd==idf.model.linear_deps, [Pb Pd] == idf.model.Pp)
                #Pb = Matrix(idf.model.Pb) #.applyfunc(lambda x: x.nsimplify())
                #Pd = Matrix(idf.model.Pd) #.applyfunc(lambda x: x.nsimplify())
                K = Matrix(idf.model.K) #(Pb.T + Kd * Pd.T)

            for c in reversed(self.delete_cols):
                K.col_del(c)

            # OLS: minimize ||tau - Y*x_base||^2 (simplify)=> minimize ||rho1.T - R1*K*delta||^2
            # sub contact forces
            contactForces = Q.T.dot(idf.model.contactForcesSum)
            if idf.opt['useRegressorRegularization']:
                p_nid = idf.model.non_id
                p_nid = list(set(p_nid).difference(set(self.delete_cols)))
                contactForces = Matrix(np.concatenate( (contactForces, np.zeros(len(p_nid)))))

            import time
            print("Step 1...", time.ctime())

            # get minimal regresion error
            rho2_norm_sqr = la.norm(idf.model.torques_stack - idf.model.YBase.dot(idf.model.xBase))**2

            # get additional regression error
            if idf.opt['useRegressorRegularization'] and len(p_nid):
                # add regularization term to cost function to include torque estimation error and CAD distance
                # get symbols that are non-id but are not in delete_cols already
                delta_nonid = Matrix(idf.model.param_syms[p_nid])
                #num_samples = YBase.shape[0]/idf.model.N_DOFS
                l = (float(idf.base_error) / len(p_nid)) * 1.5   #proportion of distance term

                p = BlockMatrix([[(K*delta)], [delta_nonid]])
                Y = BlockMatrix([[Matrix(R1),             ZeroMatrix(R1.shape[0], len(p_nid))],
                                 [ZeroMatrix(len(p_nid), R1.shape[1]), l*Identity(len(p_nid))]])
                tau_hat = np.concatenate((rho1, l*idf.model.xStdModel[p_nid]))

                #TODO: also use symengine (but we should only come here for fixed-base, so mostly smaller DOFs)
                e_rho1 = (Matrix(tau_hat) - contactForces - Y*p).as_explicit()
            else:
                try:
                    from symengine import DenseMatrix as eMatrix
                    print('using symengine')
                    edelta = eMatrix(delta.shape[0], delta.shape[1], delta)
                    eK = eMatrix(K.shape[0], K.shape[1], K)
                    eR1 = eMatrix(R1.shape[0], R1.shape[1], Matrix(R1))
                    print("Step 2.1...", time.ctime())
                    e_rho1 = eMatrix(rho1 - contactForces) - eR1*eK*edelta
                except ImportError:
                    e_rho1 = Matrix(rho1 - contactForces) - R1*K*delta

            print("Step 2...", time.ctime())

            # minimize estimation error of to-be-found parameters delta
            # (regressor dot std variables projected to base - contacts should be close to measured torques)
            u = Symbol('u')
            U_rho = BlockMatrix([[Matrix([u - rho2_norm_sqr]), e_rho1.T],
                                 [e_rho1,            I(e_rho1.shape[0])]])

            print("Step 3...", time.ctime())
            U_rho = U_rho.as_explicit()

            print("Step 4...", time.ctime())

            if idf.opt['verbose']:
                print("Add constraint LMIs")
            lmis = [LMI_PSD(U_rho)] + self.LMIs_marg
            variables = [u] + list(delta)

            #solve SDP
            objective_func = u

            if idf.opt['verbose']:
                print("Solving constrained OLS as SDP")

            # start at CAD data, might increase convergence speed (atm only works with dsdp5,
            # otherwise returns primal as solution when failing)
            prime = idf.model.xStdModel
            solution, state = sdp_helpers.solve_sdp(objective_func, lmis, variables, primalstart=prime)

            #try again with wider bounds and dsdp5 cmd line
            if state is not 'optimal':  # or not idf.paramHelpers.isPhysicalConsistent(np.squeeze(np.asarray(solution[1:]))):
                print("Trying again with dsdp5 solver")
                sdp_helpers.solve_sdp = sdp_helpers.dsdp5
                solution, state = sdp_helpers.solve_sdp(objective_func, lmis, variables, primalstart=prime, wide_bounds=True)
                sdp_helpers.solve_sdp = sdp_helpers.cvxopt_conelp

            u_star = solution[0,0]
            if u_star:
                print("found std solution with {} squared residual error".format(u_star))
            delta_star = np.matrix(solution[1:])
            idf.model.xStd = np.squeeze(np.asarray(delta_star))

            #prepend apriori values for 0'th link non-identifiable variables
            for c in self.delete_cols:
                idf.model.xStd = np.insert(idf.model.xStd, c, 0)
            idf.model.xStd[self.delete_cols] = idf.model.xStdModel[self.delete_cols]

        if idf.opt['showTiming']:
            print("Constrained SDP optimization took %.03f sec." % (t.interval))


    def identifyFeasibleStandardParametersDirect(self, idf):
        ''' use SDP optimzation to solve constrained OLS to find globally optimal physically
            feasible std parameters. Based on code from Sousa, 2014, using direct regressor from Gautier, 2013
        '''
        with helpers.Timer() as t:
            #if idf.opt['useAPriori']:
            #    print("Please disable using a priori parameters when using constrained optimization.")
            #    sys.exit(1)

            if idf.opt['verbose']:
                print("Preparing SDP...")

            #build OLS matrix
            I = Identity
            delta = Matrix(idf.model.param_syms)

            YStd = idf.YStd_nonsing
            tau = idf.model.torques_stack

            if idf.opt['useRegressorRegularization']:
                p_nid = idf.model.non_id
                #p_nid = list(set(p_nid).difference(set(self.delete_cols)))
                #l = [0.001]*len(p_nid)
                l = [(float(idf.base_error) / len(p_nid)) * 1.5]*len(p_nid)   #proportion of distance term
                YStd = np.vstack((YStd, (l*np.identity(idf.model.num_params)[p_nid].T).T))
                tau = np.concatenate((tau, l*idf.model.xStdModel[p_nid]))

            for c in reversed(self.delete_cols):
                delta.row_del(c)
            YStd = np.delete(YStd, self.delete_cols, axis=1)

            Q, R = la.qr(YStd)
            Q1 = Q[:, 0:idf.model.num_params]
            #Q2 = Q[:, idf.model.num_base_params:]
            rho1 = Q1.T.dot(tau)
            R1 = np.matrix(R[:idf.model.num_params, :idf.model.num_params])

            # OLS: minimize ||tau - Y*x_base||^2 (simplify)=> minimize ||rho1.T - R1*K*delta||^2
            # sub contact forces
            if idf.opt['useRegressorRegularization']:
                contactForcesSum = np.concatenate( (idf.model.contactForcesSum, np.zeros(len(p_nid))))
            else:
                contactForcesSum = idf.model.contactForcesSum
            contactForces = Matrix(Q.T.dot(contactForcesSum))

            import time
            print("Step 1...", time.ctime())

            # minimize estimation error of to-be-found parameters delta
            # (regressor dot std variables projected to base - contacts should be close to measured torques)
            e_rho1 = Matrix(rho1) - (R1*delta - contactForces)

            print("Step 2...", time.ctime())

            # calc estimation error of previous OLS parameter solution
            rho2_norm_sqr = la.norm(idf.model.torques_stack - idf.model.YBase.dot(idf.model.xBase))**2

            # (this is the slow part when matrices get bigger, BlockMatrix or as_explicit?)
            u = Symbol('u')
            U_rho = BlockMatrix([[Matrix([u - rho2_norm_sqr]), e_rho1.T],
                                 [e_rho1,       I(idf.model.num_params)]])
            print("Step 3...", time.ctime())
            U_rho = U_rho.as_explicit()
            print("Step 4...", time.ctime())

            if idf.opt['verbose']:
                print("Add constraint LMIs")
            lmis = [LMI_PSD(U_rho)] + self.LMIs_marg
            variables = [u] + list(delta)

            #solve SDP
            objective_func = u

            if idf.opt['verbose']:
                print("Solving constrained OLS as SDP")

            # start at CAD data, might increase convergence speed (atm only works with dsdp5,
            # otherwise returns primal as solution when failing)
            prime = idf.model.xStdModel
            solution, state = sdp_helpers.solve_sdp(objective_func, lmis, variables, primalstart=prime)

            #try again with wider bounds and dsdp5 cmd line
            if state is not 'optimal':
                print("Trying again with dsdp5 solver")
                sdp_helpers.solve_sdp = sdp_helpers.dsdp5
                solution, state = sdp_helpers.solve_sdp(objective_func, lmis, variables, primalstart=prime, wide_bounds=True)
                sdp_helpers.solve_sdp = sdp_helpers.cvxopt_conelp

            u_star = solution[0,0]
            if u_star:
                print("found std solution with {} squared residual error".format(u_star))
            delta_star = np.matrix(solution[1:])
            idf.model.xStd = np.squeeze(np.asarray(delta_star))

            #prepend apriori values for 0'th link non-identifiable variables
            for c in self.delete_cols:
                idf.model.xStd = np.insert(idf.model.xStd, c, 0)
            idf.model.xStd[self.delete_cols] = idf.model.xStdModel[self.delete_cols]

        if idf.opt['showTiming']:
            print("Constrained SDP optimization took %.03f sec." % (t.interval))


    def identifyFeasibleBaseParameters(self, idf):
        ''' use SDP optimization to solve OLS to find physically feasible base parameters (i.e. for
            which a consistent std solution exists), based on code from github.com/cdsousa/wam7_dyn_ident
        '''
        with helpers.Timer() as t:
            if idf.opt['verbose']:
                print("Preparing SDP...")

            # build OLS matrix
            I = Identity
            def mrepl(m,repl):
                return m.applyfunc(lambda x: x.xreplace(repl))

            # base and standard parameter symbols
            delta = Matrix(idf.model.param_syms)
            beta_symbs = idf.model.base_syms

            # permutation of std to base columns projection
            # (simplify to reduce 1.0 to 1 etc., important for replacement)
            Pb = Matrix(idf.model.Pb).applyfunc(lambda x: x.nsimplify())
            # permutation of std to non-identifiable columns (dependents)
            Pd = Matrix(idf.model.Pd).applyfunc(lambda x: x.nsimplify())

            # projection matrix from independents to dependents
            #Kd = Matrix(idf.model.linear_deps)
            #K = Matrix(idf.model.K).applyfunc(lambda x: x.nsimplify()) #(Pb.T + Kd * Pd.T)

            # equations for base parameters expressed in independent std param symbols
            #beta = K * delta
            beta = Matrix(idf.model.base_deps).applyfunc(lambda x: x.nsimplify())

            ## std vars that occur in base params (as many as base params, so only the single ones or chosen as independent ones)

            '''
            if idf.opt['useBasisProjection']:
                # determined through base matrix, which included other variables too
                # (find first variable in eq, chosen as independent here)
                delta_b_syms = []
                for i in range(idf.model.base_deps.shape[0]):
                    for s in idf.model.base_deps[i].free_symbols:
                        if s not in delta_b_syms:
                            delta_b_syms.append(s)
                            break
                delta_b = Matrix(delta_b_syms)
            else:
                # determined through permutation matrix from QR (not correct if base matrix is orthogonalized afterwards)
            '''
            delta_b = Pb.T*delta

            ## std variables that are dependent, i.e. their value is a combination of independent columns
            '''
            if idf.opt['useBasisProjection']:
                #determined from base eqns
                delta_not_d = idf.model.base_deps[0].free_symbols
                for e in idf.model.base_deps:
                    delta_not_d = delta_not_d.union(e.free_symbols)
                delta_d = []
                for s in delta:
                    if s not in delta_not_d:
                        delta_d.append(s)
                delta_d = Matrix(delta_d)
            else:
                # determined through permutation matrix from QR (not correct if base matrix is orthogonalized afterwards)
            '''
            delta_d = Pd.T*delta

            # rewrite LMIs for base params

            if idf.opt['useBasisProjection']:
                # (Sousa code is assuming that delta_b for each eq has factor 1.0 in equations beta.
                # this is true if using Gautier dependency matrix, otherwise
                # correct is to properly transpose eqn base_n = a1*x1 + a2*x2 + ... +an*xn to
                # 1*xi = a1*x1/ai + a2*x2/ai + ... + an*xn/ai - base_n/ai )
                transposed_beta = Matrix([solve(beta[i], delta_b[i])[0] for i in range(len(beta))])
                self.varchange_dict = dict(zip(delta_b,  beta_symbs + transposed_beta))

                #add free vars to variables for optimization
                for eq in transposed_beta:
                    for s in eq.free_symbols:
                        if s not in delta_d:
                            delta_d = delta_d.col_join(Matrix([s]))
            else:
                self.varchange_dict = dict(zip(delta_b,  beta_symbs - (beta - delta_b)))

            DB_blocks = [mrepl(Di, self.varchange_dict) for Di in self.D_blocks]
            epsilon_safemargin = 1e-6
            self.DB_LMIs_marg = list([LMI_PSD(lm - epsilon_safemargin*eye(lm.shape[0])) for lm in DB_blocks])

            Q, R = la.qr(idf.model.YBase)
            Q1 = Q[:, 0:idf.model.num_base_params]
            #Q2 = Q[:, idf.model.num_base_params:]
            rho1 = Q1.T.dot(idf.model.torques_stack)
            R1 = np.matrix(R[:idf.model.num_base_params, :idf.model.num_base_params])

            # OLS: minimize ||tau - Y*x_base||^2 (simplify)=> minimize ||rho1.T - R1*K*delta||^2
            # sub contact forces
            contactForces = Q.T.dot(idf.model.contactForcesSum)

            e_rho1 = Matrix(rho1) - (R1*beta_symbs - contactForces)

            rho2_norm_sqr = la.norm(idf.model.torques_stack - idf.model.YBase.dot(idf.model.xBase))**2
            u = Symbol('u')
            U_rho = BlockMatrix([[Matrix([u - rho2_norm_sqr]), e_rho1.T],
                                 [e_rho1, I(idf.model.num_base_params)]])
            U_rho = U_rho.as_explicit()

            if idf.opt['verbose']:
                print("Add constraint LMIs")

            lmis = [LMI_PSD(U_rho)] + self.DB_LMIs_marg
            variables = [u] + list(beta_symbs) + list(delta_d)

            # solve SDP
            objective_func = u

            if idf.opt['verbose']:
                print("Solving constrained OLS as SDP")

            # start at CAD data, might increase convergence speed (atm only works with dsdp5,
            # otherwise returns primal as solution when failing)
            prime = np.concatenate((idf.model.xBaseModel, np.array(Pd.T*idf.model.xStdModel)[:,0]))
            #import ipdb; ipdb.set_trace()
            solution, state = sdp_helpers.solve_sdp(objective_func, lmis, variables, primalstart=prime)

            #try again with wider bounds and dsdp5 cmd line
            if state is not 'optimal':
                print("Trying again with dsdp5 solver")
                sdp_helpers.solve_sdp = sdp_helpers.dsdp5
                solution, state = sdp_helpers.solve_sdp(objective_func, lmis, variables, primalstart=prime, wide_bounds=True)
                sdp_helpers.solve_sdp = sdp_helpers.cvxopt_conelp

            u_star = solution[0,0]
            if u_star:
                print("found base solution with {} error increase from OLS solution".format(u_star))
            beta_star = np.matrix(solution[1:1+idf.model.num_base_params])

            idf.model.xBase = np.squeeze(np.asarray(beta_star))

        if idf.opt['showTiming']:
            print("Constrained SDP optimization took %.03f sec." % (t.interval))


    def findFeasibleStdFromFeasibleBase(self, idf, xBase):
        ''' find a std feasible solution for feasible base solution (exists by definition) while
            minimizing param distance to a-priori parameters
        '''

        def mrepl(m, repl):
            return m.applyfunc(lambda x: x.xreplace(repl))
        I = Identity

        #symbols for std params
        delta = Matrix(idf.model.param_syms)

        # equations for base parameters expressed in independent std param symbols
        #beta = K * delta
        beta = idf.model.base_deps #.applyfunc(lambda x: x.nsimplify())

        #add explicit constraints for each base param equation and estimated value
        D_base_val_blocks = []
        for i in range(idf.model.num_base_params):
            D_base_val_blocks.append( Matrix([beta[i] - xBase[i] - 0.00001]) )
            D_base_val_blocks.append( Matrix([xBase[i] + 0.00001 - beta[i]]) )
        self.D_blocks += D_base_val_blocks

        epsilon_safemargin = 1e-6
        self.LMIs_marg = list([LMI_PSD(lm - epsilon_safemargin*eye(lm.shape[0])) for lm in self.D_blocks])

        #closest to CAD but ignore non_identifiable params
        sol_cad_dist = Matrix(idf.model.xStdModel - idf.model.param_syms)
        u = Symbol('u')
        U_rho = BlockMatrix([[Matrix([u]), sol_cad_dist.T],
                             [sol_cad_dist, I(idf.model.num_params)]])
        #                     [sol_cad_dist, I(len(idf.model.identifiable))]])
        U_rho = U_rho.as_explicit()

        lmis = [LMI_PSD(U_rho)] + self.LMIs_marg
        variables = [u] + list(idf.model.param_syms)
        objective_func = u   # 'find' problem

        solution, state = sdp_helpers.solve_sdp(objective_func, lmis, variables, primalstart=idf.model.xStdModel)

        #try again with wider bounds and dsdp5 cmd line
        if state is not 'optimal':
            print("Trying again with dsdp5 solver")
            sdp_helpers.solve_sdp = sdp_helpers.dsdp5
            # start at CAD data to find solution faster
            solution, state = sdp_helpers.solve_sdp(objective_func, lmis, variables, primalstart=idf.model.xStdModel, wide_bounds=True)
            sdp_helpers.solve_sdp = sdp_helpers.cvxopt_conelp

        u = solution[0, 0]
        print("found std solution with distance {} from CAD solution".format(u))
        idf.model.xStd = np.squeeze(np.asarray(solution[1:]))


    def findFeasibleStdFromStd(self, idf, xStd):
        ''' find closest feasible std solution for some std parameters (increases error) '''

        delta = Matrix(idf.model.param_syms)
        I = Identity

        Pd = Matrix(idf.model.Pd)
        delta_d = (Pd.T*delta)

        u = Symbol('u')
        U_delta = BlockMatrix([[Matrix([u]),       (xStd - delta).T],
                               [xStd - delta,    I(idf.model.num_params)]])
        U_delta = U_delta.as_explicit()
        lmis = [LMI_PSD(U_delta)] + self.LMIs_marg
        variables = [u] + list(delta)
        objective_func = u

        prime = idf.model.xStdModel
        solution, state = sdp_helpers.solve_sdp(objective_func, lmis, variables, primalstart=prime)

        u_star = solution[0,0]
        if u_star:
            print("found std solution with {} error increase from previous solution".format(u_star))
        delta_star = np.matrix(solution[1:])
        xStd = np.squeeze(np.asarray(delta_star))

        return xStd