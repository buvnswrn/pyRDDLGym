from Env import RDDLEnv as RDDLEnv
from Policies.Agents import RandomAgent
import numpy as np
import random

FOLDER = './Competition/Drone/Drone_con/'


def main():
    steps = 1000
    myEnv = RDDLEnv.RDDLEnv(domain=FOLDER + 'domain.rddl', instance=FOLDER + 'insta0.rddl', is_grounded=False)
    agent = RandomAgent(action_space=myEnv.action_space, num_actions=myEnv.NumConcurrentActions)
    
    from pprint import pprint
    pprint(vars(myEnv.model))
    
    total_reward = 0
    state = myEnv.reset()
    for step in range(steps):
        myEnv.render()
        action = agent.sample_action()

        next_state, reward, done, info = myEnv.step(action)
        total_reward += reward
        # print("step {}: reward: {}".format(step, reward))
        # print("state_i:", state, "-> state_f:", next_state)
        print("\nstep = {}".format(step))
        print('reward = {}'.format(reward))
        print('state = {}'.format(state))
        print('action = {}'.format(action))
        print('next_state = {}'.format(next_state))
        print('derived = {}'.format(myEnv.model.derived))
        print('interm = {}'.format(myEnv.model.interm))
        state = next_state
    print("episode ended with reward {}".format(total_reward))


if __name__ == "__main__":
    main()