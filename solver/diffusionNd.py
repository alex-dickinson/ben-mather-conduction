"""
Copyright 2017 Ben Mather

This file is part of Conduction <https://git.dias.ie/itherc/conduction/>

Conduction is free software: you can redistribute it and/or modify
it under the terms of the GNU Lesser General Public License as published by
the Free Software Foundation, either version 3 of the License, or any later version.

Conduction is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License
along with Conduction.  If not, see <http://www.gnu.org/licenses/>.
"""

try: range = xrange
except: pass

import numpy as np
from petsc4py import PETSc
from mpi4py import MPI
comm = MPI.COMM_WORLD

from . import ConductionND

class DiffusionND(ConductionND):
    """
    Implicit N-dimensional solver for the time-dependent heat equation
    over a structured grid using PETSc data structures (inherits ConductionND).

    Parameters
    ----------
     minCoord : tuple, minimum Cartesian coordinates at edge of domain
     maxCoord : tuple, maximum Cartesian coordinates at edge of domain
     res      : tuple, resolution in each dimension
     theta    : float, diffusion number that controls time discretisation [0, 1]
        0.0 = backward Euler
        0.5 = Crank-Nicholson (default, most accurate)
        1.0 = forward Euler
     kwargs   : dict, keyword arguments to pass to KSP method and preconditioner
        see PETSc documentaion for KSPType and PCType options...
        http://www.mcs.anl.gov/petsc/petsc-current/docs/manualpages/KSP/KSPType.html
        http://www.mcs.anl.gov/petsc/petsc-current/docs/manualpages/PC/PCType.html
    """
    def __init__(self, minCoord, maxCoord, res, theta=0.5, **kwargs):

        super(DiffusionND, self).__init__(minCoord, maxCoord, res, **kwargs)

        self.temperature_new = self.create_meshVariable("temperature_new")

        # theta rule in time, centred differences in space
        if theta < 0 or theta > 1:
            raise ValueError("theta must be in the range [0, 1]")
        self.theta = theta

        # get maximum spacing
        delta = np.zeros(self.dim)
        all_delta = np.zeros(self.dim)
        for i in range(self.dim):
            dx = np.diff(self.grid_coords[i])
            delta[i] = dx.max()

        comm.Allreduce([delta, MPI.DOUBLE], [all_delta, MPI.DOUBLE], op=MPI.MAX)
        self.delta = all_delta

        self._ldiag = self.lvec.duplicate()


    def calculate_dt(self):
        """
        Calculate optimal timestep size
        """
        kappa = self.diffusivity
        delta = self.delta
        max_kappa = kappa._gdata.max()[1]
        dt = np.sum(delta**2)/(4.0*max_kappa)
        return dt


    def construct_matrix(self, in_place=True, derivative=False, scale=1.0):
        """
        Construct the coefficient matrix
        i.e. matrix A in Ax = b

        This extends the ConductionND method by including time-dependence
        through a scale variable.
        """
        ldiag = self._ldiag
        mat = self.mat

        if scale > 0:
            mat = super(DiffusionND, self).construct_matrix(in_place, derivative)
            mat.scale(-scale)
        else:
            # preallocate identity matrix
            diag = self.gvec.duplicate()
            diag.set(1.0)
            mat.assemblyBegin()
            mat.setDiagonal(diag)
            mat.assemblyEnd()
            mat.scale(0.0)

        diag = mat.getDiagonal()
        diag += 1.0 # add self node

        # overwrite Dirichlet BCs
        self.dm.globalToLocal(diag, ldiag)
        ldiag.array[self.dirichlet_mask] = 1.0
        self.dm.localToGlobal(ldiag, diag)
        mat.setDiagonal(diag)
        return mat


    def construct_rhs(self, in_place=True, scale=1.0):
        """
        Construct the right-hand-side vector
        i.e. vector b in Ax = b

        This extends the ConductionND method by including time-dependence
        through a scale variable.
        """
        if in_place:
            rhs = self.rhs
        else:
            rhs = self.create_meshVariable('rhs')

        if scale > 0:
            # vectorise stencil similar to matrix construction
            n = self.n
            cols = self.cols
            index = self.index
            vals = self.vals

            temp  = self.temperature[:].reshape(n)
            kappa = self.diffusivity[:].reshape(n)
            k = np.pad(kappa, self.width, 'constant', constant_values=0)
            T = np.pad(temp,  self.width, 'constant', constant_values=0)

            for i in range(0, self.stencil_width):
                obj = self.closure[i]

                cols[i] = index[obj].ravel()

                distance = np.linalg.norm(self.coords[cols[i]] - self.coords, axis=1)
                distance[distance==0] = 1e-12 # protect against dividing by zero
                delta = scale/distance**2

                vals[i] = delta*(0.5*(k[obj] + kappa)*(T[obj] - temp)).ravel()
            
            # zero off-grid coordinates
            vals[cols < 0] = 0.0
            vals[-1] = 0.0 # centre point
            vec = vals.sum(axis=0)

            # add heat sources
            vec += scale*self.heat_sources[:]
        else:
            vec = np.zeros(self.nn)

        # add current temperature
        vec += self.temperature[:]

        # enforce BCs
        for wall in self.bc:
            val  = self.bc[wall]['val']
            flux = self.bc[wall]['flux']
            mask = self.bc[wall]['mask']
            if flux:
                vec[mask] += val
            else:
                vec[mask] = val

        rhs[:] = vec
        return rhs


    def timestep(self, steps=1, dt=None):
        """
        Solve a timestep
        """
        if type(dt) == type(None):
            dt = self.calculate_dt()

        theta = self.theta
        Lscale = dt*theta
        Rscale = dt*(1.0 - theta)

        # construct a constant matrix
        mat = self.construct_matrix(scale=Lscale)

        for step in range(steps):
            rhs = self.construct_rhs(scale=Rscale)
            T = self.solve(mat, rhs)

        return T
