import numpy as np
import jax
import jax.numpy as jnp
import jax.random as random
import optax
from typing import Dict, Generator
import warnings

from pyRDDLGym.Core.ErrorHandling.RDDLException import RDDLNotImplementedError
from pyRDDLGym.Core.Jax.JaxRDDLCompiler import JaxRDDLCompiler
from pyRDDLGym.Core.Jax.JaxRDDLSimulator import JaxRDDLSimulator
from pyRDDLGym.Core.Parser.rddl import RDDL


class FuzzyLogic:
    
    def _and(self, a, b):
        raise NotImplementedError
    
    def _not(self, x):
        return 1.0 - x
    
    def _or(self, a, b):
        return self._not(self._and(self._not(a), self._not(b)))
    
    def _xor(self, a, b):
        return self._and(self._or(a, b), self._not(self._and(a, b)))
    
    def _implies(self, a, b):
        return self._or(self._not(a), b)
    
    def _forall(self, x, axis=None):
        raise NotImplementedError
    
    def _exists(self, x, axis=None):
        return self._not(self._forall(self._not(x), axis=axis))
    
    def _if_then_else(self, p, a, b):
        raise NotImplementedError
    

class ProductLogic(FuzzyLogic):
    
    def _and(self, a, b):
        return a * b

    def _or(self, a, b):
        return a + b - a * b
    
    def _implies(self, a, b):
        return 1.0 - a * (1.0 - b)

    def _forall(self, x, axis=None):
        return jnp.prod(x, axis=axis)
    
    def _if_then_else(self, p, a, b):
        return p * a + (1.0 - p) * b


class MinimumLogic(FuzzyLogic):
    
    def _and(self, a, b):
        return jnp.minimum(a, b)
    
    def _or(self, a, b):
        return jnp.maximum(a, b)
    
    def _forall(self, x, axis=None):
        return jnp.min(x, axis=axis)
    
    def _exists(self, x, axis=None):
        return jnp.max(x, axis=axis)
    
    def _if_then_else(self, p, a, b):
        return p * a + (1.0 - p) * b


class JaxRDDLBackpropCompiler(JaxRDDLCompiler):
    
    def __init__(self, rddl: RDDL, logic: FuzzyLogic=ProductLogic()) -> None:
        super(JaxRDDLBackpropCompiler, self).__init__(rddl, allow_discrete=False)
        
        self.LOGICAL_OPS = {
            '^': logic._and,
            '|': logic._or,
            '~': logic._xor,
            '=>': logic._implies,
            '<=>': jnp.equal
        }
        self.LOGICAL_NOT = logic._not
        self.AGGREGATION_OPS = {
            'sum': jnp.sum,
            'avg': jnp.mean,
            'prod': jnp.prod,
            'min': jnp.min,
            'max': jnp.max,
            'forall': logic._forall,
            'exists': logic._exists
        }
        self.IF_THEN_ELSE = logic._if_then_else
        
    def _jax_logical(self, expr, op, params):
        warnings.warn('Logical operator {} will be converted to fuzzy variant.'.format(op),
                      FutureWarning, stacklevel=2)
        
        return super(JaxRDDLBackpropCompiler, self)._jax_logical(expr, op, params)
    
    def _jax_aggregation(self, expr, op, params):
        warnings.warn('Aggregation operator {} will be converted to fuzzy variant.'.format(op),
                      FutureWarning, stacklevel=2)
        
        return super(JaxRDDLBackpropCompiler, self)._jax_aggregation(expr, op, params)
        
    def _jax_control(self, expr, op, params):
        valid_ops = {'if'}
        JaxRDDLBackpropCompiler._check_valid_op(expr, valid_ops)
        JaxRDDLBackpropCompiler._check_num_args(expr, 3)
        
        warnings.warn('If statement will be converted to fuzzy variant.',
                      FutureWarning, stacklevel=2)
                
        pred, if_true, if_false = expr.args        
        jax_pred = self._jax(pred, params)
        jax_true = self._jax(if_true, params)
        jax_false = self._jax(if_false, params)
        
        if_then_else = self.IF_THEN_ELSE
        
        def _f(x, key):
            val1, key, err1 = jax_pred(x, key)
            val2, key, err2 = jax_true(x, key)
            val3, key, err3 = jax_false(x, key)
            sample = if_then_else(val1, val2, val3)
            err = err1 | err2 | err3
            return sample, key, err
            
        return _f

    def _jax_kron(self, expr, params):
        warnings.warn('KronDelta will be ignored.', FutureWarning, stacklevel=2)            
        arg, = expr.args
        return self._jax(arg, params)
    
    def _jax_poisson(self, expr, params):
        raise RDDLNotImplementedError(
            'No reparameterization implemented for Poisson.' + '\n' + 
            JaxRDDLBackpropCompiler._print_stack_trace(expr))
    
    def _jax_gamma(self, expr, params):
        raise RDDLNotImplementedError(
            'No reparameterization implemented for Gamma.' + '\n' + 
            JaxRDDLBackpropCompiler._print_stack_trace(expr))
            
    
class JaxRDDLBackpropPlanner:
    
    def __init__(self,
                 rddl: RDDL, 
                 key: jax.random.PRNGKey,
                 n_steps: int,
                 n_batch: int,
                 action_bounds: Dict={},
                 initializer: jax.nn.initializers.Initializer=jax.nn.initializers.zeros,
                 optimizer: optax.GradientTransformation=optax.adam(0.1),
                 aggregation=jnp.mean,
                 logic: FuzzyLogic=ProductLogic()) -> None:
        self.key = key
        
        compiler = JaxRDDLBackpropCompiler(rddl, logic=logic)
        sim = JaxRDDLSimulator(compiler, key)
        subs = sim.subs
        cpfs = sim.cpfs
        reward_fn = sim.reward
        primed_unprimed = sim.state_unprimed
        
        NORMAL = JaxRDDLBackpropCompiler.ERROR_CODES['NORMAL']
        
        # plan initialization
        action_info = {}
        for pvar in rddl.domain.action_fluents.values():
            aname = pvar.name       
            atype = JaxRDDLBackpropCompiler.RDDL_TO_JAX_TYPE[pvar.range]
            ashape = (n_steps,)
            avalue = subs[aname]
            if hasattr(avalue, 'shape'):
                ashape = ashape + avalue.shape
            action_info[aname] = (atype, ashape)
            if atype != JaxRDDLBackpropCompiler.REAL:
                subs[aname] = np.asarray(subs[aname], dtype=np.float32)
                
        # perform one step of a roll-out        
        def _step(carry, actions):
            x, key, err = carry            
            x.update(actions)
            
            # calculate all the CPFs (e.g., s') and r(s, a, s') in order
            for name, cpf_fn in cpfs.items():
                x[name], key, cpf_err = cpf_fn(x, key)
                err |= cpf_err
            reward, key, rew_err = reward_fn(x, key)
            err |= rew_err
            
            # set s <- s'
            for primed, unprimed in primed_unprimed.items():
                x[unprimed] = x[primed]
                
            return (x, key, err), reward
        
        # perform a single roll-out
        def _rollout(plan, x0, key):
            
            # set s' <- s at the first epoch
            x0 = x0.copy()               
            for primed, unprimed in primed_unprimed.items():
                x0[primed] = x0[unprimed]
            
            # generate roll-outs and cumulative reward
            (x, key, err), rewards = jax.lax.scan(_step, (x0, key, NORMAL), plan)
            cuml_reward = jnp.sum(rewards)
            
            return cuml_reward, x, key, err
        
        # force action ranges     
        finite_action_bounds = {}
        for name, bounds in action_bounds.items():
            lb, ub = bounds
            if np.isfinite(lb) and np.isfinite(ub) and lb <= ub:
                finite_action_bounds[name] = bounds
        
        def _force_action_ranges(plan):
            new_plan = {}
            for name, action in plan.items():
                atype, _ = action_info[name]
                
                # coerce action to the right type
                if atype == bool:
                    new_action = jax.nn.sigmoid(action)
                elif atype == JaxRDDLBackpropCompiler.INT:
                    new_action = jnp.asarray(
                        action, dtype=JaxRDDLBackpropCompiler.REAL)
                else:
                    new_action = action
                
                # bound actions to the desired range
                if atype != bool and name in finite_action_bounds:
                    lb, ub = finite_action_bounds[name]
                    new_action = lb + (ub - lb) * jax.nn.sigmoid(new_action)
                    
                new_plan[name] = new_action
            return new_plan
        
        self.force_action_ranges = jax.jit(_force_action_ranges)
        
        # do a batch of roll-outs
        def _batched(value):
            value = jnp.asarray(value)
            batched_shape = (n_batch,) + value.shape
            return jnp.broadcast_to(value, shape=batched_shape) 
        
        def _batched_rollouts(plan, key):
            x_batch = jax.tree_map(_batched, subs)
            keys = jax.random.split(key, num=n_batch)
            returns, x_batch, keys, errs = jax.vmap(
                _rollout, in_axes=(None, 0, 0))(plan, x_batch, keys)
            key = keys[-1]
            return returns, key, x_batch, errs
        
        # aggregate all sampled returns
        def _loss(plan, key):
            plan = _force_action_ranges(plan)
            returns, key, x_batch, errs = _batched_rollouts(plan, key)
            loss_value = -aggregation(returns)
            errs = jax.lax.reduce(errs, NORMAL, jnp.bitwise_or, (0,))
            return loss_value, (key, x_batch, errs)
        
        # gradient descent update
        def _update(plan, opt_state, key):
            grad, (key, x_batch, errs) = jax.grad(_loss, has_aux=True)(plan, key)
            updates, opt_state = optimizer.update(grad, opt_state)
            plan = optax.apply_updates(plan, updates)       
            return plan, opt_state, key, x_batch, errs
        
        self.loss = jax.jit(_loss)
        self.update = jax.jit(_update)
        
        # initialization
        def _initialize(key):
            plan = {}
            for action, (_, ashape) in action_info.items():
                key, subkey = random.split(key)
                plan[action] = initializer(
                    subkey, ashape, dtype=JaxRDDLBackpropCompiler.REAL)
            opt_state = optimizer.init(plan)
            return plan, opt_state, key
        
        self.initialize = jax.jit(_initialize)

    def optimize(self, n_epochs: int) -> Generator[Dict, None, None]:
        ''' Compute an optimal straight-line plan for the RDDL domain and instance.
        
        @param n_epochs: the maximum number of steps of gradient descent
        '''
        plan, opt_state, self.key = self.initialize(self.key)
        
        best_plan = self.force_action_ranges(plan)
        best_loss = float('inf')
        
        for step in range(n_epochs):
            plan, opt_state, self.key, _, _ = self.update(plan, opt_state, self.key)
                       
            loss_val, (self.key, rollouts, errs) = self.loss(plan, self.key)
            errs = JaxRDDLBackpropCompiler.get_error_codes(errs)
            fixed_plan = self.force_action_ranges(plan)

            if loss_val < best_loss:
                best_plan = fixed_plan
                best_loss = loss_val
            
            callback = {'step': step,
                        'plan': fixed_plan,
                        'best_plan': best_plan,
                        'loss': loss_val,
                        'best_loss': best_loss,
                        'rollouts': rollouts,
                        'errors': errs}
            yield callback
        
