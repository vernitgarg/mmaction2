from abc import ABCMeta, abstractmethod
from collections import OrderedDict

import torch
import torch.distributed as dist
import torch.nn as nn


class BaseLocalizer(nn.Module, metaclass=ABCMeta):
    """Base class for localizers.

    All localizers should subclass it. All subclass should overwrite:
    Methods:`forward_train`, supporting to forward when training.
    Methods:`forward_test`, supporting to forward when testing.
    """

    def __init__(self):
        super().__init__()

    def init_weights(self):
        pass

    @abstractmethod
    def forward_train(self, imgs, labels):
        pass

    @abstractmethod
    def forward_test(self, imgs):
        pass

    def forward(self, imgs, label=None, return_loss=True):
        if return_loss:
            if label is None:
                raise ValueError('Label should not be None.')
            return self.forward_train(imgs, label)
        else:
            return self.forward_test(imgs)

    @staticmethod
    def _parse_losses(losses):
        """Parse the raw outputs (losses) of the network.

        Args:
            losses (dict): Raw output of the network, which usually contain
                losses and other necessary information.

        Returns:
            tuple[Tensor, dict]: (loss, log_vars), loss is the loss tensor
                which may be a weighted sum of all losses, log_vars contains
                all the variables to be sent to the logger.
        """
        log_vars = OrderedDict()
        for loss_name, loss_value in losses.items():
            if isinstance(loss_value, torch.Tensor):
                log_vars[loss_name] = loss_value.mean()
            elif isinstance(loss_value, list):
                log_vars[loss_name] = sum(_loss.mean() for _loss in loss_value)
            else:
                raise TypeError(
                    f'{loss_name} is not a tensor or list of tensors')

        loss = sum(_value for _key, _value in log_vars.items()
                   if 'loss' in _key)

        log_vars['loss'] = loss
        for loss_name, loss_value in log_vars.items():
            # reduce loss when distributed training
            if dist.is_available() and dist.is_initialized():
                loss_value = loss_value.data.clone()
                dist.all_reduce(loss_value.div_(dist.get_world_size()))
            log_vars[loss_name] = loss_value.item()

        return loss, log_vars

    def train_step(self, data_batch, optimizer, **kwargs):
        losses = self.forward(**data_batch)

        loss, log_vars = self._parse_losses(losses)

        outputs = dict(
            loss=loss,
            log_vars=log_vars,
            num_samples=len(next(iter(data_batch.values()))))

        return outputs

    def val_step(self, data_batch, optimizer, **kwargs):
        results = self.forward(return_loss=False, **data_batch)

        outputs = dict(results=results)

        return outputs
