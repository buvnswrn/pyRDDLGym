import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt

import numpy as np
from PIL import Image

from pyRDDLGym.Core.Compiler.RDDLModel import PlanningModel
from pyRDDLGym.Visualizer.StateViz import StateViz


class ChartVisualizer(StateViz):

    def __init__(self, model: PlanningModel,
                 steps_history=None,
                 figure_size=[10, 10],
                 dpi=100,
                 fontsize=10,
                 boolcol=['red', 'green'],
                 loccol='black') -> None:
        self._model = model
        self._figure_size = figure_size
        self._dpi = dpi
        self._fontsize = fontsize
        self._boolcol = boolcol
        self._loccol = loccol
        
        self._fig, self._ax = None, None
        self._data = None
        self._img = None
        
        if steps_history is None:
            steps_history = model.horizon
        self._steps = steps_history
        self._state_hist = {}
        self._state_shapes = {}
        self._labels = {}
        for (state, values) in self._model.states.items():
            values = np.atleast_1d(values)
            self._state_hist[state] = np.full(
                shape=(len(values), self._steps),
                fill_value=np.nan
            )
            self._state_shapes[state] = self._model.object_counts(
                self._model.param_types[state]
            )
            self._labels[state] = list(map(
                ','.join, self._model.variations(self._model.param_types[state])
            ))
        self._step = 0
        
    def convert2img(self, fig, ax): 
        # ax.set_position((0, 0, 1, 1))
        fig.canvas.draw()

        data = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8)
        data = data.reshape(fig.canvas.get_width_height()[::-1] + (3,))
        img = Image.fromarray(data)

        self._data = data
        self._img = img
        return img

    def render(self, state):
        
        # update the state info
        if self._step >= self._steps:
            for (_, values) in self._state_hist.items():
                values[:,:-1] = values[:, 1:]
        states = {name: np.full(shape=shape, fill_value=np.nan)
                  for (name, shape) in self._state_shapes.items()}
        for (name, value) in state.items():
            var, objects = self._model.parse(name)
            states[var][self._model.indices(objects)] = value
        index = min(self._step, self._steps - 1)
        for (name, values) in states.items():
            self._state_hist[name][:, index] = np.ravel(values, order='C')
            
        # draw color plots
        self._fig, self._ax = plt.subplots(
            len(self._state_hist), 1,
            squeeze=True,
            figsize=self._figure_size
        ) 
        if len(self._state_hist) == 1:
            self._ax = (self._ax,)
            
        for (y, (state, values)) in enumerate(self._state_hist.items()):
            values = values[::-1,:]
            
            self._ax[y].xaxis.label.set_fontsize(self._fontsize)
            self._ax[y].yaxis.label.set_fontsize(self._fontsize)
            self._ax[y].title.set_text(state)
            self._ax[y].set_xlabel('decision epoch')
            self._ax[y].set_ylabel(state)
            self._ax[y].axvline(
                x=index + 0.5, ymin=0.0, ymax=1.0,
                color=self._loccol, linestyle='--', linewidth=2, alpha=0.9
            )
            
            if self._model.variable_ranges[state] == 'bool':
                self._ax[y].pcolormesh(
                    values, edgecolors=self._loccol, linewidth=0.5, 
                    cmap=matplotlib.colors.ListedColormap(self._boolcol)
                )            
                patches = [
                    matplotlib.patches.Patch(color=self._boolcol[0], label='false'),
                    matplotlib.patches.Patch(color=self._boolcol[1], label='true')
                ]
                self._ax[y].legend(handles=patches, loc='upper right')
                
                labels = self._labels[state]
                self._ax[y].yaxis.set_ticks([0, len(labels)])
                self._ax[y].yaxis.set(ticks=np.arange(0.5, len(labels), 1), ticklabels=labels) 
                self._ax[y].set_yticklabels(
                    labels,
                    fontdict={"fontsize": self._fontsize},
                    rotation=30
                )
                
            else:
                for (i, var) in enumerate(self._labels[state]):
                    self._ax[y].plot(values[i, :], 'o-', label=var)
                self._ax[y].set_xlim([0, values[i, :].size])
                self._ax[y].legend(loc='upper right')
            
            
        self._step = self._step + 1
        plt.tight_layout()
        
        img = self.convert2img(self._fig, self._ax)
        
        plt.clf()
        plt.close()

        return img
    