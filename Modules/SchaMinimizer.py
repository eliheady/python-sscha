 # -*- coding: utf-8 -*-

"""
This is part of the program python-sscha
Copyright (C) 2018  Lorenzo Monacelli

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>. 
"""

"""
This file contains the SSCHA minimizer tool
It is possible to use it to perform the anharmonic minimization 
"""

#import Ensemble
import numpy as np
try:
    __MATPLOTLIB__ = True
    import matplotlib.pyplot as plt
except:
    __MATPLOTLIB__ = False
import cellconstructor as CC
import cellconstructor.Methods
import time

import sys, os

import Ensemble

# Rydberg to cm-1 and meV conversion factor
__RyToCm__  = 109691.40235
__RyTomev__ = 13605.698066
__RyToev__ = 13.605698066
__RyBohr3_to_GPa__ = 14710.513242194795
__K_to_Ry__ = 6.336857346553283e-06
__EPSILON__ = 1e-4
__evA3_to_GPa__ = 160.21766208
__RyBohr3_to_evA3__ = __RyBohr3_to_GPa__ / __evA3_to_GPa__

class SSCHA_Minimizer:
    
    def __init__(self, ensemble = None, root_representation = "normal",
                 kong_liu_ratio = 0.5, meaningful_factor = 0.1,
                 minimization_algorithm = "sdes", lambda_a = 1):
        """
        This class create a minimizer to perform the sscha minimization.
        It performs the sscha minimization.
        
        Parameters
        ----------
            ensemble : Ensemble.Ensemble()
                This is the Ensemble. This class contains the pool of configurations to be
                used in the minimizations.
            root_representation : string
                Chose between "normal", "sqrt" and "root4". These are the nonlinear change
                of variable to speedup the code.
            kong_liu_ratio : float
                The ration of the Kong-Liu effective sample size below which
                the minimization is stopped and a new ensemble needs to be
                generated to proceed.
            meaningful_factor : float
                The ration between the gradient and its error below which
                the minimization is considered to be converged.
            minimization_algorithm : string
                The minimization algoirthm used. One between 'sdes', 'cgrf' or
                'auto'. They behave as follow:
                    - 'sdes' => Steepest Descent
                    - 'cgrf' => Congjugate gradient
                    - 'auto' => Uses cgrf if the error lower than the gradient, 'sdes' otherwise.
                
                NOTE: Only sdes is currently implemented.
            lambda_a : float
                The force constant minimization step.
        """
        
        self.ensemble = ensemble
        self.root_representation = root_representation
        
        
        # The symmetries
        self.symmetries = None
        
        # The minimization step
        self.min_step_dyn = lambda_a
        self.min_step_struc = 1
        
        if ensemble is not None:
            self.dyn = self.ensemble.current_dyn.Copy()
        else:
            self.dyn = None
        self.dyn_path = ""
        self.population = 0
        
        # Projection. This is chosen to fix some constraint on the minimization
        self.projector_dyn = None
        self.projector_struct = None
        
        # The gradient before the last step was performed (Used for the CG)
        self.prev_grad = None
        
        # Preconditioning variables
        self.precond_wyck = True
        self.precond_dyn = True
        
        self.minim_struct = True
        
        # This is a debugging flag
        # If true the preconditioning of the original ensemble
        # is used
        self.fake_precond = False
        
        # The stopping criteria on which gradient is evaluated
        self.gradi_op = "gc"
        
        # Define the stress offset
        self.stress_offset = np.zeros((3,3), dtype = np.float64, order = "F")
        
        # If true the symmetries are neglected
        self.neglect_symmetries = False
        
        
        # Setup the statistical threshold
        self.kong_liu_ratio = kong_liu_ratio
        
        # Setup the meaningful_factor
        self.meaningful_factor = meaningful_factor
        
        # Setup the minimization algorithm
        self.minimization_algorithm = minimization_algorithm

        # This is used to polish the ensemble energy
        self.eq_energy = 0
        
        # This is the maximum number of steps (if negative = infinity)
        self.max_ka = -1
        
        # Initialize the variable for convergence
        self.__converged__ = False
        
        # Initialize all the variables to store the minimization
        self.__fe__ = []
        self.__fe_err__ = []
        self.__gc__ = []
        self.__gc_err__ = []
        self.__gw__ = []
        self.__gw_err__ = []
        self.__KL__ = []
        
        
    def minimization_step(self, custom_function_gradient = None):
        """
        Perform the single minimization step.
        This modify the self.dyn matrix and updates the ensemble
    
        Parameters
        ----------
            custom_function_gradient : pointer to function ( ndarray(nq x 3nat x 3nat), ndarray(nat, 3))
                A function that can be used both to print particular component of the gradient
                or to impose some constraints on the minimization (like lock the position of some atoms).
                It takes as input the two gradient (the dynamical matrix one and the structure one), and
                modifies them (or does some I/O on it).
        """
        
        # Setup the symmetries
        qe_sym = CC.symmetries.QE_Symmetry(self.dyn.structure)
        
        #qe_sym.SetupQPoint(verbose = False)
        
        
        # Get the gradient of the free-energy respect to the dynamical matrix
        #dyn_grad, err = self.ensemble.get_free_energy_gradient_respect_to_dyn()
        #dyn_grad, err = self.ensemble.get_fc_from_self_consistency(True, True)
        #dyn_grad, err = self.ensemble.get_fc_from_self_consistency(True, True)
        t1 = time.time()
        if self.precond_dyn:
            dyn_grad, err = self.ensemble.get_preconditioned_gradient(True, True, preconditioned=1)
        else:
            dyn_grad, err = self.ensemble.get_preconditioned_gradient(True, True, preconditioned=0)

        
        # Perform the symmetrization
#        qe_sym.ImposeSumRule(dyn_grad)
#        qe_sym.SymmetrizeDynQ(dyn_grad, np.array([0,0,0]))
#        qe_sym.ImposeSumRule(err)
#        qe_sym.SymmetrizeDynQ(err, np.array([0,0,0]))
        if not self.neglect_symmetries:
            qe_sym.SymmetrizeFCQ(dyn_grad, np.array(self.dyn.q_stars), asr = "custom")
            qe_sym.SymmetrizeFCQ(err, np.array(self.dyn.q_stars), asr = "crystal")
        else:
            for i in range(len(self.dyn.q_tot)):
                qe_sym.ImposeSumRule(dyn_grad[i, :,:], asr = "custom")
                qe_sym.ImposeSumRule(err[i, :, :], asr = "custom")
        t2 = time.time()
        print "Time elapsed to compute the dynamical matrix gradient:", t2 - t1, "s"
        
#        # get the gradient in the supercell
#        new_grad_tmp = CC.Phonons.GetSupercellFCFromDyn(dyn_grad, np.array(self.dyn.q_tot),
#                                                        self.dyn.structure, 
#                                                        self.dyn.structure.generate_supercell(self.ensemble.supercell))
#        
#        #np.savetxt("NewGradSC.dat", np.real(new_grad_tmp))
       
        
        # This gradient is already preconditioned, if the precondition
        # is turned off we have to modify the gradient
#        
#        if self.fake_precond:
#            if self.dyn.nqirr != 1:
#                raise ValueError("Implement this for the supercell")
#            dyn_grad = ApplyLambdaTensor(self.dyn, dyn_grad)    
#            err = ApplyLambdaTensor(self.dyn, err)
#            qe_sym.ImposeSumRule(dyn_grad[0,:,:])
#            qe_sym.ImposeSumRule(err[0,:,:])
#        
#        # This is a debugging strategy (we use the preconditioning)
#        if self.fake_precond:
#            dyn_grad = ApplyFCPrecond(self.ensemble.dyn_0, dyn_grad)
#            err = ApplyFCPrecond(self.ensemble.dyn_0, err)
#            qe_sym.ImposeSumRule(dyn_grad)
#            qe_sym.ImposeSumRule(err)
            
        
            
        
        
        
        # If the structure must be minimized perform the step
        if self.minim_struct:
            t1 = time.time()
            # Get the gradient of the free-energy respect to the structure
            struct_grad, struct_grad_err =  self.ensemble.get_average_forces(True)
            #print "SHAPE:", np.shape(struct_grad)
            struct_grad_reshaped = - struct_grad.reshape( (3 * self.dyn.structure.N_atoms))
            t2 = time.time()
            
            print "Time elapsed to compute the structure gradient:", t2 - t1, "s"
            
            
            # Preconditionate the gradient for the wyckoff minimization
            if self.precond_wyck:
                struct_precond = GetStructPrecond(self.ensemble.current_dyn)
                struct_grad_precond = struct_precond.dot(struct_grad_reshaped)
                struct_grad = struct_grad_precond.reshape( (self.dyn.structure.N_atoms, 3))
            
            
            # Apply the symmetries to the forces
            if not self.neglect_symmetries:
                qe_sym.SetupQPoint()
                qe_sym.SymmetrizeVector(struct_grad)
                qe_sym.SymmetrizeVector(struct_grad_err)

            # Perform the gradient restriction
            if custom_function_gradient is not None:
                custom_function_gradient(dyn_grad, struct_grad)    
                
                #print "applying sum rule and symmetries:"
                #qe_sym.SymmetrizeFCQ(dyn_grad, np.array(self.dyn.q_stars), asr = "custom")
                #print "SECOND DIAG:", np.linalg.eigvalsh(dyn_grad[0, :, :])
            
            # Append the gradient modulus to the minimization info
            self.__gw__.append(np.sqrt( np.sum(struct_grad**2)))
            self.__gw_err__.append(np.sqrt( np.einsum("ij, ij", struct_grad_err, struct_grad_err) / qe_sym.QE_nsymq))
        
            
            # Perform the step for the structure
            #print "min step:", self.min_step_struc
            self.dyn.structure.coords -= self.min_step_struc * struct_grad
        else:

            # Prepare the gradient imposing the constraints
            if custom_function_gradient is not None:
                custom_function_gradient(dyn_grad, np.zeros(self.dyn.structure.N_atoms, 3)) 
            
            # Append the gradient modulus to the minimization info
            self.__gw__.append(0)
            self.__gw_err__.append(0)


        
        # Store the gradient in the minimization
        self.__gc__.append(np.real(np.einsum("abc,acb", dyn_grad, dyn_grad)))
        self.__gc_err__.append(np.real(np.einsum("abc, acb", err, err)))
            
        # Perform the step for the dynamical matrix respecting the root representation
        new_dyn = PerformRootStep(np.array(self.dyn.dynmats, order = "C"), dyn_grad,
                                  self.min_step_dyn, root_representation = self.root_representation,
                                  minimization_algorithm = self.minimization_algorithm)
        
        # Update the dynamical matrix
        for iq in range(len(self.dyn.q_tot)):
            self.dyn.dynmats[iq] = new_dyn[iq, : ,: ]
        
        self.dyn.save_qe("Prova")
        

        # Update the ensemble
        self.update()
        
        # Update the previous gradient
        self.prev_grad = dyn_grad
        
    def setup_from_namelist(self, input_file):
        """
        SETUP THE MINIMIZATION 
        ======================
        
        This function setups all the parameters of the minimization using a namelist.
        It is compatible with the old sscha code, and very usefull to save the 
        input parameters in a simple input filename.
        
        Parameters
        ----------
            line_list : list of string
                List of strings obtained from the method readlines. 
                The content must match the Quantum ESPRESSO file format
        """
        
        # Get the dictionary
        namelist = CC.Methods.read_namelist(input_file)
        
        # Extract the principal namelist
        if not "inputscha" in namelist.keys():
            raise ValueError("Error, a main namelist 'inputscha' is required.")
            
        namelist = namelist["inputscha"]
        #print namelist
        
        # Check for keywords
        keys = namelist.keys()
        
        if "lambda_a" in keys:
            self.min_step_dyn = np.float64(namelist["lambda_a"])
        
        if "lambda_w" in keys:
            self.min_step_struc = np.float64(namelist["lambda_w"])
            
        if "precond_wyck" in keys:
            self.precond_wyck = bool(namelist["precond_wyck"])
            
        if "preconditioning" in keys:
            self.precond_dyn = bool(namelist["preconditioning"])
            
        if "root_representation" in keys:
            self.root_representation = namelist["root_representation"]
        
        if "neglect_symmetries" in keys:
            self.neglect_symmetries = namelist["neglect_symmetries"]
            
        if "n_random_eff" in keys:
            if not "n_random" in keys:
                raise IOError("Error, if you want to impose the minimum KL\n"
                              "       effective sample size, you must give also n_random")
            self.kong_liu_ratio =  np.float64(namelist["n_random_eff"]) / int(namelist["n_random"])
            
        if "meaningful_factor" in keys:
            self.meaningful_factor = np.float64(namelist["meaningful_factor"])
            
        if "eq_energy" in keys:
            self.eq_energy = np.float64(namelist["eq_energy"])
            
        if "fildyn_prefix" in keys:
            # nqirr must be present
            if not "nqirr" in keys:
                raise IOError("Error, if an input dynamical matrix is specified, you must add the nqirr options")
            
            self.dyn = CC.Phonons.Phonons(namelist["fildyn_prefix"], nqirr = int(namelist["nqirr"]))
            self.dyn_path = namelist["fildyn_prefix"]
            
            if not "data_dir" in keys:
                self.ensemble = Ensemble.Ensemble(self.dyn, 0)
                
                if "t" in keys:
                    self.ensemble.current_T = np.float64(namelist["t"])
                    if not "tg" in keys:
                        self.ensemble.T0 = self.ensemble.current_T
                
                if "tg" in keys:
                    self.ensemble.T0 = np.float64(namelist["tg"])
                    
                if "supercell_size" in keys:
                    self.ensemble.supercell = [int(x) for x in namelist["supercell_size"]]
            
        if "max_ka" in keys:
            self.max_ka = int(namelist["max_ka"])
            
        if "stress_offset" in keys:
            # Load the offset from a filename
            try:
                # Try to interpret it as a number
                off = np.float64(namelist["stress_offset"])
                self.stress_offset = off * np.eye(3, dtype = np.float64, order = "F")
            except:
                # Interpret it as a file
                if not os.path.exists(namelist["stress_offset"]):
                    raise IOError("Error, the file %s specified as a stress_offset cannot be open" % namelist["stress_offset"])
                
            self.stress_offset = np.loadtxt(namelist["stress_offset"])
            
        if "gradi_op" in keys:
            if not namelist["gradi_op"] in ["gc", "gw", "all"] :
                raise ValueError("Error, gradi_op supports only 'gc', 'gw' or 'all'")
            
            self.gradi_op = namelist["gradi_op"]
        
        # Ensemble keywords
        if "data_dir" in keys:
            # We can load an ensemble, check for the population number
            if not "population" in keys:
                raise IOError("Error, population required if the ensemble is provided")
            if not "n_random" in keys:
                raise IOError("Error, n_random required when providing an ensemble")
            
            if not "fildyn_prefix" in keys:
                raise IOError("Error, the dynamical matrix that generated the ensemble must be provided")
            
            
            #print "data_dir seen"
            
            # Setup the ensemble
            self.ensemble = Ensemble.Ensemble(self.dyn, 0)
            
            if "t" in keys:
                self.ensemble.current_T = np.float64(namelist["t"])
                if not "tg" in keys:
                    self.ensemble.T0 = self.ensemble.current_T
            
            if "tg" in keys:
                self.ensemble.T0 = np.float64(namelist["tg"])
                
            if "supercell_size" in keys:
                self.ensemble.supercell = [int(x) for x in namelist["supercell_size"]]
                
            # Load the data dir
            self.population = int(namelist["population"])
            self.ensemble.load(namelist["data_dir"], int(namelist["population"]), int(namelist["n_random"]))
        
    def print_info(self):
        """
        PRINT SETTINGS ON OUTPUT
        ========================
        
        This subroutine is for debugging purposes, it will print the settings about 
        the minimizer on the standard output.
        """
        
        print ""
        print ""
        print " ====== MINIMIZER SETTINGS ====== "
        print ""
        print ""
        print " --- GENERAL SETTINGS --- "
        print " original temperature = ", self.ensemble.T0
        print " current temperature = ", self.ensemble.current_T
        print " number of configurations = ", self.ensemble.N
        print " max number of steps (infinity if negative) = ", self.max_ka
        print " meaningful factor = ", self.meaningful_factor
        print " gradient to watch (for stopping) = ", self.gradi_op
        print " Kong-Liu minimum effective sample size = ", self.ensemble.N * self.kong_liu_ratio
        print " (Kong-Liu ratio = ", self.kong_liu_ratio, ")"
        print " compute the stress tensor = ", self.ensemble.has_stress
        print " total number of atoms = ", self.dyn.structure.N_atoms * np.prod(self.ensemble.supercell)
        print ""
        print ""
        print " --- STRUCT MINIMIZATION --- "
        print " minim_struct = ", self.minim_struct
        print " preconditioning = ", self.precond_wyck
        print " minimization step (lambda_w) = ", self.min_step_struc
        print ""
        print ""
        print " --- FC MINIMIZATION --- "
        print " preconditioning = ", self.precond_dyn
        print " minimization step (lambda_a) = ", self.min_step_dyn
        print " supercell size = ", " ".join([str(x) for x in self.ensemble.supercell])
        
        # Get the current frequencies
        w, pols = self.dyn.GenerateSupercellDyn(self.ensemble.supercell).DyagDinQ(0)
        w *= __RyToCm__
        
        # Get the starting frequencies
        w0, p0 = self.ensemble.dyn_0.GenerateSupercellDyn(self.ensemble.supercell).DyagDinQ(0)
        w0 *= __RyToCm__
        
        print ""
        print " Current dyn frequencies [cm-1] = ", "\t".join(["%.2f" % x for x in w])
        print ""
        print " Start dyn frequencies [cm-1] = ", "\t".join(["%.2f" % x for x in w0])
        print ""
        print ""
        
    def is_converged(self):
        """
        Simple method to check if the simulation is converged or
        requires a new population to be runned.
        
        Result
        ------
            bool : 
                True if the simulation ended for converging.
        """
        return self.__converged__
        
    def update(self):
        """
        UPDATE IMPORTANCE SAMPLING
        ==========================
        
        
        This methods makes the self.dyn coincide with self.ensemble.current_dyn, and overwrites the stochastic
        weights of the current_dyn.
        
        Call this method each time you modify the dynamical matrix of the minimization to avoid errors.
        
        NOTE: it is equivalent to call self.ensemble.update_weights(self.dyn, self.ensemble.current_T)
        """
        
        self.ensemble.update_weights(self.dyn, self.ensemble.current_T)
        
        
    def get_free_energy(self, return_error = False):
        """
        SSCHA FREE ENERGY
        =================
        
        Obtain the SSCHA free energy for the system.
        This is done by integrating the free energy along the hamiltonians, starting
        from current_dyn to the real system.
        
        The result is in Rydberg.
        
        NOTE: this method just recall the self.ensemble.get_free_energy function.
        
        .. math::
            
            \\mathcal F = \\mathcal F_0 + \\int_0^1 \\frac{d\\mathcal F_\\lambda}{d\\lambda} d\\lambda
        
        Where :math:`\\lambda` is the parameter for the adiabatic integration of the hamiltonian.
        
        .. math::
            
            H(\\lambda) = H_0 + (H - H_0) \\lambda
        
        here :math:`H_0` is the sscha harmonic hamiltonian, while :math:`H_1` is the real hamiltonian 
        of the system.
        
        Returns
        -------
            float
                The free energy in the current dynamical matrix and at the ensemble temperature
        
        """
        
        #TODO: CHECK THE CONSISTENCY BETWEEN THE DYNAMICAL MATRICES
        # Check if the dynamical matrix has correctly been updated
        #if np.sum( self.dyn != self.ensemble.current_dyn):
        #    raise ValueError("Error, the ensemble dynamical matrix has not been updated. You forgot to call self.update() before")
        
        return self.ensemble.get_free_energy(return_error = return_error) / np.prod(self.ensemble.supercell)
    
    def init(self):
        """
        INITIALIZE THE MINIMIZATION
        ===========================
        
        This subroutine initialize the variables needed by the minimization.
        Call this before the first time you invoke the run function.
        """
        
        # Symmetrize the starting dynamical matrix and apply the sum rule
        qe_sym = CC.symmetries.QE_Symmetry(self.dyn.structure)
        fcq = np.array(self.dyn.dynmats)
        qe_sym.SymmetrizeFCQ(fcq, self.dyn.q_stars, asr = "custom")
        for iq in range(len(self.dyn.q_tot)):
            self.dyn.dynmats[iq] = fcq[iq, :, :]
        
        self.check_imaginary_frequencies()
        
        # Clean all the minimization variables
        self.__fe__ = []
        self.__fe_err__ = []
        self.__converged__ = False
        self.__gc__ = []
        self.__gc_err__ = []
        self.__KL__ = []
        self.__gw__ = []
        self.__gw_err__ = []
        
        # Get the free energy
        fe, err = self.get_free_energy(True)
        self.__fe__.append(fe - self.eq_energy)
        self.__fe_err__.append(err)
        
        # Get the initial gradient
        #grad = self.ensemble.get_fc_from_self_consistency(True, False)
        grad = self.ensemble.get_preconditioned_gradient(True)
        self.prev_grad = grad
        
        # For now check that if root representation is activated
        # The preconditioning must be deactivated
        if self.root_representation != "normal" and self.precond_dyn:
            raise ValueError("Error, deactivate the preconditioning if a root_representation is used.")
        
#
#        # Initialize the symmetry
#        qe_sym = CC.symmetries.QE_Symmetry(self.dyn.structure)
#        qe_sym.SetupQPoint(verbose = True)
#
#        struct_grad, struct_grad_err = self.ensemble.get_average_forces(True)
#
#        qe_sym.SymmetrizeVector(struct_grad)
#        qe_sym.SymmetrizeVector(struct_grad_err)
#        
#        # Get the gradient modulus
#        gc = np.trace(grad.dot(grad))
#        gc_err = np.trace(grad_err.dot(grad_err))
#
#        self.__gw__.append(np.sqrt( np.einsum("ij, ij", struct_grad, struct_grad)))
#        self.__gw_err__.append(np.sqrt( np.einsum("ij, ij", struct_grad_err, struct_grad_err) / qe_sym.QE_nsymq))
#
#        self.__gc__.append(gc)
#        self.__gc_err__.append(gc_err)
        
        # Compute the KL ratio
        self.__KL__.append(self.ensemble.get_effective_sample_size())
        
        # Prepare the minimization step rescaling to its best
        if not self.precond_wyck:
            self.min_step_struc *= GetBestWykoffStep(self.dyn)

    
    def run(self, verbose = 1, custom_function_pre = None, custom_function_post = None,
            custom_function_gradient = None):
        """
        RUN THE SSCHA MINIMIZATION
        ==========================
        
        This function uses all the setted up parameters to run the minimization
        
        The minimization is stopped only when one of the stopping criteria are met.
        
        The verbose level can be chosen.
        
        Parameters
        ----------
            verbose : int
                The verbosity level.
                    - 0 : Noting is printed
                    - 1 : For each step only the free energy, the modulus of the gradient and 
                        the Kong-Liu effective sample size is printed.
                    - 2 : The dynamical matrix at each step is saved on output with a progressive integer
            custom_function_pre : pointer to function (self)
                It is a custom function that takes as an input the current
                structure. At each step this function is invoked. This allows
                to print particular analysis during the minimization that
                the user want to define to better control what is it happening
                to the system. 
                This function is called before the minimization step has been performed.
                The info on the system saved in the self minimization reguards the previous step.
            custom_function_post : pointer to function(self)
                The same as the previous argument, but this function is invoked after 
                the minimization step has been perfomed. The data about free energy,
                gradient and effective sample size have been updated.
            custom_function_gradient : pointer to function (ndarray(NQ, 3*nat, 3*nat), ndarray(nat, 3))
                A pointer to a function that takes as an input the two gradients, and modifies them.
                It is called after the two gradients have been computed, and it is used to 
                impose some constraint on the minimization.
        """
        
        # Eliminate the convergence flag
        self.__converged__ = False
        
        # TODO: Activate a new pipe to avoid to stop the execution of the python 
        #       code when running the minimization. This allows for interactive plots
        running = True
        
        
        while running:
            # Invoke the custom fuction if any
            if custom_function_pre is not None:
                custom_function_pre(self)
            
            # Store the original dynamical matrix
            old_dyn = self.dyn.Copy()
            
            if verbose >= 1:
                print ""
                print " # ---------------- NEW MINIMIZATION STEP --------------------"
                print "Step ka = ", len(self.__fe__)
            
            # Perform the minimization step
            t1 = time.time()
            self.minimization_step(custom_function_gradient)
            t2 = time.time()
            if verbose >=1:
                print "Time elapsed to perform the minimization step:", t2 - t1, "s"
            
            
            if self.check_imaginary_frequencies():
                print "Immaginary frequencies found."
                print "Minimization aborted."
                break
            
            # Compute the free energy and its error
            fe, err = self.get_free_energy(True)
            fe -= self.eq_energy
            self.__fe__.append(np.real(fe))
            self.__fe_err__.append(np.real(err))
            
            harm_fe = self.dyn.GetHarmonicFreeEnergy(self.ensemble.current_T) / np.prod(self.ensemble.supercell)
            anharm_fe = np.real(fe - harm_fe)
            
            # Compute the KL ratio
            self.__KL__.append(self.ensemble.get_effective_sample_size())
            
            # Print the step
            if verbose >= 1:
                print ""
                print "Harmonic contribution to free energy = %16.8f meV" % (harm_fe * __RyTomev__)
                print "Anharmonic contribution to free energy = %16.8f +- %16.8f meV" % (anharm_fe * __RyTomev__,
                                                                                         np.real(err) * __RyTomev__)
                print "Free energy = %16.8f +- %16.8f meV" % (self.__fe__[-1] * __RyTomev__, 
                                                              self.__fe_err__[-1] * __RyTomev__)
                
                print "FC gradient modulus = %16.8f +- %16.8f bohr^2" % (self.__gc__[-1] * __RyTomev__, 
                                                                       self.__gc_err__[-1] * __RyTomev__)
                print "Struct gradient modulus = %16.8f +- %16.8f meV/A" % (self.__gw__[-1] * __RyTomev__,
                                                                            self.__gw_err__[-1] * __RyTomev__)
                print "Kong-Liu effective sample size = ", self.__KL__[-1]
                print ""
            
            if verbose >= 2:
                # Print the dynamical matrix at each step
                ka = len(self.__fe__)
                self.dyn.save_qe("minim_dyn_step%d_" % ka)
            
            
            # Get the stopping criteria
            running = not self.check_stop()
            print "Check the stopping criteria: Running = ", running
            
            
            if len(self.__fe__) > self.max_ka and self.max_ka > 0:
                print "Maximum number of steps reached."
                running = False
            
            # Invoke the custom function (if any)
            if custom_function_post is not None:
                custom_function_post(self)
            
            # Flush the output to avoid asyncronous printing
            sys.stdout.flush()
            
        # If your stopped not for convergence then 
        # restore the last dynamical matrix
        if not self.is_converged():
            print ""
            print "Restoring the last good dynamical matrix."
            self.dyn = old_dyn
            
            print "Updating the importance sampling..."
            self.update()
            print ""
            
        
    def finalize(self, verbose = 1):
        """
        FINALIZE
        ========
        
        This method finalizes the minimization, and prints on stdout the
        results of the current minimization.
        
        Parameters
        ----------
            verbose : int, optional
                The verbosity level. If 0 only the final free energy and gradient is printed.
                If 1 the stress tensor is also printed. If 2 also the final structure and frequencies
                are printed.
        """
        
        
        
        print ""
        print " * * * * * * * * "
        print " *             * "
        print " *   RESULTS   * "
        print " *             * "
        print " * * * * * * * * "
        print ""
        
        print ""
        print "Minimization ended after %d steps" % len(self.__gc__)
        print ""

        print "Free energy = %16.8f +- %16.8f meV" % (self.__fe__[-1] * __RyTomev__, 
                                                      self.__fe_err__[-1] * __RyTomev__)
        print "FC gradient modulus = %16.8f +- %16.8f bohr^2" % (self.__gc__[-1] * __RyTomev__, 
                                                               self.__gc_err__[-1] * __RyTomev__)
        print "Struct gradient modulus = %16.8f +- %16.8f meV/A" % (self.__gw__[-1] * __RyTomev__,
                                                                    self.__gw_err__[-1] * __RyTomev__)
        print "Kong-Liu effective sample size = ", self.__KL__[-1]
        print ""
        
        if self.ensemble.has_stress and verbose >= 1:
            print ""
            print " ==== STRESS TENSOR [GPa] ==== "
            stress, err = self.get_stress_tensor()
            
            # Convert in GPa
            stress *= __RyBohr3_to_GPa__
            err *= __RyBohr3_to_GPa__
            
            print "%16.8f%16.8f%16.8f%10s%16.8f%16.8f%16.8f" % (stress[0,0], stress[0,1], stress[0,2], "",
                                                                err[0,0], err[0,1], err[0,2])
            print "%16.8f%16.8f%16.8f%10s%16.8f%16.8f%16.8f" % (stress[1,0], stress[1,1], stress[1,2], "    +-    ",
                                                                err[1,0], err[1,1], err[1,2])
            
            print "%16.8f%16.8f%16.8f%10s%16.8f%16.8f%16.8f" % (stress[2,0], stress[2,1], stress[2,2], "",
                                                                err[2,0], err[2,1], err[2,2])
            
            print ""
        
        
        if verbose >= 2:
            print " ==== FINAL STRUCTURE [A] ==== "
            nat = self.dyn.structure.N_atoms
            for i in range(nat):
                print "%5s %16.8f%16.8f%16.8f" % (self.dyn.structure.atoms[i], 
                                                  self.dyn.structure.coords[i,0],
                                                  self.dyn.structure.coords[i,1],
                                                  self.dyn.structure.coords[i,2])
            print ""
            print " ==== FINAL FREQUENCIES [cm-1] ==== "
            super_dyn = self.dyn.GenerateSupercellDyn(self.ensemble.supercell)
            w, pols = super_dyn.DyagDinQ(0)
            trans = CC.Methods.get_translations(pols, super_dyn.structure.get_masses_array())
            
            for i in range(len(w)):
                print "Mode %5d:   freq %16.8f cm-1  | is translation? " % (i+1, w[i] * __RyToCm__), trans[i] 
        
            print ""
        
            

    def check_imaginary_frequencies(self):
        """
        The following subroutine check if the current matrix has imaginary frequency. In this case
        the minimization is stopped.
        """

        # Get the frequencies
        superdyn = self.dyn.GenerateSupercellDyn(self.ensemble.supercell)
        w, pols = superdyn.DyagDinQ(0)

        # Get translations
        trans_mask = ~CC.Methods.get_translations(pols, superdyn.structure.get_masses_array())

        # Remove translations
        w = w[trans_mask]
        pols = pols[:, trans_mask]

        # Frequencies are ordered, check if the first one is negative.
        if w[0] < 0:
            print "Total frequencies (excluding translations):"
            superdyn0 = self.ensemble.dyn_0.GenerateSupercellDyn(self.ensemble.supercell)
            wold, pold = superdyn0.DyagDinQ(0)
            
            trans_mask = ~CC.Methods.get_translations(pold, superdyn0.structure.get_masses_array())
            wold = wold[trans_mask] * __RyToCm__
            pold = pold[:, trans_mask]
            total_mask = range(len(w))
            ws = np.zeros(len(w))
            for i in range(len(w)):
                # Look for the fequency association
                scalar = np.abs(np.einsum("a, ab", np.conj(pols[:, i]), pold[:, total_mask]))
                index = total_mask[np.argmax(scalar)]
                ws[index] = w[i] * __RyToCm__
                total_mask.pop(np.argmax(scalar))
                
                
            print "\n".join(["%d) %.4f  | %.4f cm-1" % (i, x, wold[i]) for i, x in enumerate(ws)])
            print ""
            return True
        return False
            
        
    def check_stop(self):
        """
        CHECK THE STOPPING CONDITION
        ============================
        
        Check the stopping criteria and returns True if the stopping
        condition is satisfied
        
        Result
        ------
            bool : 
                True if the minimization must be stopped, False otherwise
        
        """
        
        # Check the gradient
        last_gc = self.__gc__[-1]
        last_gc_err = self.__gc_err__[-1]
        last_gw = self.__gw__[-1]
        last_gw_err = self.__gw_err__[-1]
        
        gc_cond = (last_gc < last_gc_err * self.meaningful_factor)
        gw_cond = (last_gw < last_gw_err * self.meaningful_factor)
        
        total_cond = False
        
        if gc_cond:
            print ""
            print "The gc gradient satisfy the convergence condition."
        if gw_cond:
            print ""
            print "The gw gradient satisfy the convergence condition."
        
        if self.gradi_op == "gc":
            total_cond = gc_cond
        elif self.gradi_op == "gw":
            total_cond = gw_cond
        elif self.gradi_op == "all":
            total_cond = gc_cond and gw_cond
        else:
            raise ValueError("Error, gradi_op must be one of 'gc', 'gw' or 'all'")
        
        if total_cond:
            self.__converged__ = True
            print "The system satisfy the convergence criteria according to the input."
            return True
        
        # Check the KL
        kl = self.ensemble.get_effective_sample_size()
        
        if kl / float(self.ensemble.N) < self.kong_liu_ratio:
            self.__converged__ = False
            print "KL:", kl, "KL/N:", kl / float(self.ensemble.N), "KL RAT:", self.kong_liu_ratio
            print "  According to your input criteria"
            print "  you are out of the statistical sampling." 
            return True

        # Check if there are imaginary frequencies
        im_freq = self.check_imaginary_frequencies()
        if im_freq:
            print "ERROR: imaginary frequencies found in the minimization"
            sys.stderr.write("ERROR: imaginary frequencies found in the minimization\n")
            return True
            
        return False
            
    def plot_results(self, save_filename = None, plot = True):
        """
        PLOT RESULTS
        ============
        
        This usefull methods uses matplotlib to generate a plot of the
        minimization.
        
        Parameters
        ----------
            save_filename : optional, string
                If present the plotted data will be saved in
                a text file specified by input.
        
            plot : optiona, bool
                If false no plot is performed. This allows only to save result
                even if you do not have any access in a X server.
        """
        
        # Check if the length of the gc is not good, and append the last
        # gradient
        if len(self.__gc__) != len(self.__fe__):
            #grad, grad_err = self.ensemble.get_fc_from_self_consistency(True, True)
            grad, grad_err = self.ensemble.get_preconditioned_gradient(True, True)
            
            # Initialize the symmetry
            qe_sym = CC.symmetries.QE_Symmetry(self.dyn.structure)
            qe_sym.SetupQPoint(verbose = True)
    
            struct_grad, struct_grad_err = self.ensemble.get_average_forces(True)
    
            qe_sym.SymmetrizeVector(struct_grad)
            qe_sym.SymmetrizeVector(struct_grad_err)
            
            # Get the gradient modulus
            gc = np.einsum("abc, acb", grad, grad)
            gc_err = np.einsum("abc, acb", grad_err, grad_err)
    
            self.__gw__.append(np.sqrt( np.einsum("ij, ij", struct_grad, struct_grad)))
            self.__gw_err__.append(np.sqrt( np.einsum("ij, ij", struct_grad_err, struct_grad_err) / qe_sym.QE_nsymq))
    
            self.__gc__.append(gc)
            self.__gc_err__.append(gc_err)
        
        # Convert the data in numpy arrays
        fe = np.array(self.__fe__) * __RyTomev__
        fe_err = np.array(self.__fe_err__) * __RyTomev__
        
        gc = np.array(self.__gc__) * __RyTomev__
        gc_err = np.array(self.__gc_err__) * __RyTomev__
        
        gw = np.array(self.__gw__) * __RyTomev__
        gw_err = np.array(self.__gw_err__) * __RyTomev__
        
        kl = np.array(self.__KL__, dtype = np.float64)
        
        steps = np.arange(len(fe))
    
        
        # Check if the results need to be saved on a file
        if save_filename is not None:            
            #print "Lengths:", len(fe), len(gc), len(gw), len(kl), len(steps)       
            print "Saving the minimization results..."
            save_data = [steps, fe, fe_err, gc, gc_err, gw, gw_err, kl]
            np.savetxt(save_filename, np.real(np.transpose(save_data)),
                       header = "Steps; Free energy +- error [meV]; FC gradient +- error [bohr^2]; Structure gradient +- error [meV / A]; Kong-Liu N_eff")
            print "Minimization data saved in %s." % save_filename
        
        
        # Plot
        if plot:
            if not __MATPLOTLIB__:
                print "MATPLOTLIB NOT FOUND."
                raise ImportError("Error, matplotlib required to plot")
            plt.figure()
            plt.title("Free energy")
            plt.errorbar(steps, fe, yerr = fe_err, label = "Free energy")
            plt.ylabel(r"$F$ [meV]")
            plt.xlabel("steps")
            plt.tight_layout()
        
            plt.figure()
            plt.title("FC matrix gradient")
            plt.errorbar(steps, gc, yerr = gc_err, label = "gradient")
            plt.ylabel(r"$|\vec g|$ [bohr^2]")
            plt.xlabel("steps")
            plt.tight_layout()
            
            plt.figure()
            plt.title("Structure gradient")
            plt.errorbar(steps, gw, yerr = gw_err, label = "gradient")
            plt.ylabel(r"$|\vec g|$ [meV / A]")
            plt.xlabel("steps")
            plt.tight_layout()
            
            plt.figure()
            plt.title("Kong-Liu effective sample size")
            plt.plot(steps, kl)
            plt.ylabel(r"$\frac{N_{eff}}{N_0}$")
            plt.xlabel("steps")
            plt.tight_layout()
        
            plt.show()
            
            
    def get_stress_tensor(self):
        """
        GET THE STRESS TENSOR
        =====================
        
        For a full documentation, please refer to the same function of the 
        Ensemble class.
        This subroutine just link to that one. A stress offset is added if defined
        in the input variable of the current class.
        
        NOTE: if the ensemble has not the stress tensors, an exception will be raised
        
        """
        
        
        return self.ensemble.get_stress_tensor(self.stress_offset)
    

def get_root_dyn(dyn_fc, root_representation):
    """
    Get the root dyn matrix
    
    
    This method computes the root equivalent of the dynamical matrix
    """
    # TODO: To be ultimated
    pass

def PerformRootStep(dyn_q, grad_q, step_size=1, root_representation = "sqrt", minimization_algorithm = "sdes"):
    """
    ROOT MINIMIZATION STEP
    ======================
    
    As for the [Monacelli, Errea, Calandra, Mauri, PRB 2017], the nonlinear
    change of variable is used to perform the step.
    
    It works as follows:
    
    .. math::
        
        \\Phi \\rightarrow \\sqrt{x}{\\Phi}
        
        \\frac{\\partial F}{\\partial \\Phi} \\rightarrow \\frac{\\partial F}{\\partial \\sqrt{x}{\\Phi}}
        
        \\sqrt{x}{\\Phi^{(n)}} \\stackrel{\\frac{\\partial F}{\\partial \\sqrt{x}{\\Phi}}}{\\longrightarrow} \\sqrt{x}{\\Phi^{(n+1)}}
        
        \\Phi^{(n+1)} = \\left(\\sqrt{x}{\\Phi^{(n+1)}})^{x}
        
    Where the specific update step is determined by the minimization_algorithm, while the :math:`x` order 
    of the root representation is determined by the root_representation argument.
    
    Parameters
    ----------
        dyn_q : ndarray( NQ x 3nat x 3nat )
            The dynamical matrix in q space. The Nq are the total number of q.
        grad_q : ndarray( NQ x 3nat x 3nat )
            The gradient of the dynamical matrix.
        step_size : float
            The step size for the minimization
        root_representation : string
            choice between "normal", "sqrt" and "root4". The value of :math:`x` will be, respectively,
            1, 2, 4.
        minimization_algorithm : string
            The minimization algorithm to be used for the update.
    
    Result
    ------
        new_dyn_q : ndarray( NQ x 3nat x 3nat )
            The updated dynamical matrix in q space
    """
    ALLOWED_REPRESENTATION = ["normal", "root4", "sqrt", "root2"]
    
    if not root_representation in ALLOWED_REPRESENTATION:
        raise ValueError("Error, root_representation is %s must be one of %s." % (root_representation,
                                                                                  ", ".join(ALLOWED_REPRESENTATION)))
    # Allow also for the usage of root2 instead of sqrt
    if root_representation == "root2":
        root_representation = "sqrt"
    
    # Apply the diagonalization
    nq = np.shape(dyn_q)[0]
    
    # Check if gradient and dyn_q have the same number of q points
    if nq != np.shape(grad_q)[0]:
        raise ValueError("Error, the number of q point of the dynamical matrix %d and gradient %d does not match!" % (nq, np.shape(grad_q)[0]))
    
    # Create the root representation
    new_dyn = np.zeros(np.shape(dyn_q), dtype = np.complex128)
    new_grad = np.zeros(np.shape(dyn_q), dtype = np.complex128)

    # Copy
    new_dyn[:,:,:] = dyn_q
    new_grad[:,:,:] = grad_q

    # Cycle over all the q points
    if root_representation != "normal":
        for iq in range(nq):
            # Dyagonalize the matrix
            eigvals, eigvects = np.linalg.eigh(dyn_q[iq, :, :])
            
            # Regularize acustic modes
            if iq == 0:
                eigvals[eigvals < 0] = 0.
            
            # The sqrt conversion
            new_dyn[iq, :, :] = np.einsum("a, ba, ca", np.sqrt(eigvals), np.conj(eigvects), eigvects)
            new_grad[iq, :, :] = new_dyn[iq, :, :].dot(grad_q[iq, :, :]) + grad_q[iq, :, :].dot(new_dyn[iq, :, :])
            
            # If root4 another loop needed
            if root_representation == "root4":                
                new_dyn[iq, :, :] = np.einsum("a, ba, ca", np.sqrt(np.sqrt(eigvals)), np.conj(eigvects), eigvects)
                new_grad[iq, :, :] = new_dyn[iq, :, :].dot(new_grad[iq, :, :]) + new_grad[iq, :, :].dot(new_dyn[iq, :, :])
    
    # Perform the step
    # For now only steepest descent implemented
    if minimization_algorithm == "sdes":
        new_dyn -= new_grad * step_size
    else:
        raise ValueError("Error, the given minimization_algorithm %s is not implemented." % minimization_algorithm)
    
    
    if root_representation != "normal":
        for iq in range(nq):
            # The square root conversion
            new_dyn[iq, :, :] = new_dyn[iq, :,:].dot(new_dyn[iq, :,:])
            
            # The root4 conversion
            if root_representation == "root4":
                new_dyn[iq, :, :] = new_dyn[iq, :,:].dot(new_dyn[iq, :,:])
    
    # Return the matrix
    return new_dyn
            
            


def ApplyLambdaTensor(current_dyn, matrix, T = 0):
    """
    INVERSE PRECONDITIONING
    =======================
    
    This function perform the inverse of the precondtioning: it applies the Hessian
    matrix to the preconditioned gradient to obtain the real one. This is
    a test function.
        
    
    Parameters
    ----------
        current_dyn : 3*nat x 3*nat
            The current force-constant matrix to compute the Lambda tensor
        matrix : 3*nat x 3*nat
            The matrix on which you want to apply the Lambda tensor.
        T : float
            The temperature
            
    Result
    ------
        new_matrix : 3*nat x 3*nat
            The matrix after the Lambda application
    """
    
    w, pols = current_dyn.DyagDinQ(0)
    
    # Get the translations
    trans = ~CC.Methods.get_translations(pols, current_dyn.structure.get_masses_array())
    
    # Restrict only to non translational modes
    w = np.real(w[trans])
    pols = np.real( pols[:, trans])
    
    nat = current_dyn.structure.N_atoms
    
    # Redefine the polarization vectors
    m = current_dyn.structure.get_masses_array()
    for i in range(nat):
        pols[3*i : 3*i + 3,:] /= np.sqrt(m[i])
        
    # Get the bose occupation number
    nmodes = len(w)
    f_munu = np.zeros( (nmodes, nmodes), dtype = np.float64)
    
    
    n_w = np.zeros( nmodes, dtype = np.float64)
    dn_dw = np.zeros(nmodes, dtype = np.float64)
    if T != 0:
        beta = 1 / (__K_to_Ry__ * T)
        n_w = 1 / (np.exp(w * beta) - 1)
        dn_dw = - beta / (2 * np.cosh(w * beta) - 1)
        
    # Prepare the multiplicating function
    for i in range(nmodes):
        md = np.abs((w - w[i]) / w[i]) > __EPSILON__
        f_munu[i, md] = (n_w[md] + n_w[i] + 1) / (w[i] + w[md]) - (n_w[i] - n_w[md]) / (w[i] - w[md])
        f_munu[i, ~md] = (2 *n_w[i] + 1) /(2* w[i]) - dn_dw[i]
        f_munu[i, :] /= - 4 * w[i] * w
        
    # Perform the Einstein summation contracting everithing
    return np.einsum("ab, ia, jb, ca, db,cd -> ij", f_munu, pols, pols,
                     pols, pols, matrix)
    

def ApplyFCPrecond(current_dyn, matrix, T = 0):
    """
    PURE FORCE-CONSTANT PRECONDITIONING
    ===================================
    
    This function perform the precondition on a given matrix, by applying
    the inverse of the lambda function
        
    
    Parameters
    ----------
        current_dyn : 3*nat x 3*nat
            The current force-constant matrix to compute the Lambda tensor
        matrix : 3*nat x 3*nat
            The matrix on which you want to apply the Lambda tensor.
        T : float
            The temperature
            
    Result
    ------
        new_matrix : 3*nat x 3*nat
            The matrix after the Lambda application
    """
    
    w, pols = current_dyn.DyagDinQ(0)
    
    # Get the translations
    trans = ~CC.Methods.get_translations(pols, current_dyn.structure.get_masses_array())
    
    # Restrict only to non translational modes
    w = np.real(w[trans])
    pols = np.real( pols[:, trans])
    
    nat = current_dyn.structure.N_atoms
    
    # Multiply for the masses
    m = current_dyn.structure.get_masses_array()
    for i in range(nat):
        pols[3*i : 3*i + 3, : ] *= np.sqrt(m[i])
        
    # Get the bose occupation number
    nmodes = len(w)
    f_munu = np.zeros( (nmodes, nmodes), dtype = np.float64)
    
    
    n_w = np.zeros( nmodes, dtype = np.float64)
    dn_dw = np.zeros(nmodes, dtype = np.float64)
    if T != 0:
        beta = 1 / (__K_to_Ry__ * T)
        n_w = 1 / (np.exp(w * beta) - 1)
        dn_dw = - beta / (2 * np.cosh(w * beta) - 1)
        
    # Prepare the multiplicating function
    for i in range(nmodes):
        md = np.abs((w - w[i]) / w[i]) > __EPSILON__
        f_munu[i, md] = (n_w[md] + n_w[i] + 1) / (w[i] + w[md]) - (n_w[i] - n_w[md]) / (w[i] - w[md])
        f_munu[i, ~md] = (2 *n_w[i] + 1) / w[i] - dn_dw[i]
        f_munu[i, :] /= 4 * w[i] * w
    
    f_munu = 1 / f_munu
        
    # Perform the Einstein summation contracting everithing
    return np.einsum("ab, ia, jb, ca, db,cd -> ij", f_munu, pols, pols,
                     pols, pols,  matrix)
    
    


def GetStructPrecond(current_dyn):
    """
    GET THE PRECONDITIONER FOR THE STRUCTURE MINIMIZATION
    =====================================================
    
    NOTE: the Phi is in Ry/bohr^2 while the forces are in Ry/A
    NOTE: the output preconditioner (that must be interfaced with forces) is in A^2/Ry
    
    The preconditioner of the structure minimization is computed directly from the
    dynamical matrix. It is the fake inverse (projected out the translations).
    
    .. math::
        
        \\Phi_{\\alpha\\beta}^{-1} = \\frac{1}{\\sqrt{M_\\alpha M_\\beta}} \\sum_\\mu \\frac{e_\\mu^\\alpha e_\\mu^\\beta}{\\omega_\\mu^2}
        
    Where the sum is restricted to the non translational modes.
    
    Parameters
    ----------
        current_dyn : Phonons()
            The current dynamical matrix
        
    Returns
    -------
        preconditioner : ndarray 3nat x 3nat
            The inverse of the force constant matrix, it can be used as a preconditioner.
            
    """
    
    # Dyagonalize the current dynamical matrix
    w, pols = current_dyn.DyagDinQ(0)
    
    # Get some usefull array
    mass = current_dyn.structure.get_masses_array()
    nat = current_dyn.structure.N_atoms
    
    _m_ = np.zeros( 3*nat, dtype = np.float64)
    for i in range(nat):
        _m_[3 * i: 3*i + 3] = mass[i]
        
    _msi_ = 1 / np.sqrt(_m_)
    
    # Select translations
    not_trans = ~CC.Methods.get_translations(pols, mass)
    
    # Delete the translations from the dynamical matrix
    w = w[not_trans]
    pols = np.real(pols[:, not_trans])
    
    wm2 = 1 / w**2
    
    # Compute the precondition using the einsum
    precond = np.einsum("a,b,c,ac,bc -> ab", _msi_, _msi_, wm2, pols, pols)
    return precond * CC.Phonons.BOHR_TO_ANGSTROM**2


def GetBestWykoffStep(current_dyn):
    """
    GET THE BEST WYCKOFF STEP
    =========================
    
    This is an alternative way to the preconditioning, in which the best wyckoff step
    is choosen rescaled on the current dynamical matrix.
    
    NOTE: It works with real space matrices.
    
    .. math::
        
        STEP = \\frac{1}{\\max \\lambda(\\Phi)}
        
    Where :math:`\\lambda(\\Phi)` is the generic eigenvalue of the force constant matrix.
    This is because :math:`\\Phi` is correct Hessian of the free energy respect to
    the structure in the minimum.
    
    The best step is returned in [Angstrom^2 / Ry]. 
    
    Parameters
    ----------
        current_dyn : ndarray 3n_at x 3n_at
            The force constant matrix :math:`\\Phi`. It should be in Ry/bohr^2. 
    """
    
    return 1 / np.max(np.real(np.linalg.eigvals(current_dyn.dynmats[0]))) * CC.Phonons.BOHR_TO_ANGSTROM**2
    
    
    
    
