import os
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions.normal import Normal
from torch.distributions import kl_divergence
from torchvision.utils import save_image

def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        try:
            nn.init.xavier_uniform_(m.weight.data)
            m.bias.data.fill_(0)
        except AttributeError:
            print("Skipping initialization of ", classname)


class VAE(nn.Module):
    def __init__(self, input_dim, dim, z_dim):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = dim
        self.z_dim = z_dim
        # 维度200以下
        self.encoder = nn.Sequential(
            nn.Conv2d(input_dim, dim, 4, 2, 1),
            nn.BatchNorm2d(dim),
            nn.ReLU(True),

            nn.Conv2d(dim, dim * 2, 4, 2, 1),
            nn.BatchNorm2d(dim * 2),
            nn.ReLU(True),

            nn.Conv2d(dim * 2, dim * 4, 4, 2, 1),
            nn.BatchNorm2d(dim * 4),
            nn.ReLU(True),

            nn.Conv2d(dim * 4, dim * 8, 4, 2, 1),
            nn.BatchNorm2d(dim * 8),
            nn.ReLU(True),

            nn.Conv2d(dim * 8, dim * 12, 4, 2, 1),
            nn.BatchNorm2d(dim * 12),
            nn.ReLU(True),

            nn.Conv2d(dim * 12, z_dim * 2, 4, 2, 1),
            nn.BatchNorm2d(z_dim * 2),

        )

        self.decoder = nn.Sequential(
            nn.ConvTranspose2d(z_dim, dim * 12, 4, 2, 1),
            nn.BatchNorm2d(dim * 12),
            nn.ReLU(True),

            nn.ConvTranspose2d(dim * 12, dim * 8, 4, 2, 1),
            nn.BatchNorm2d(dim * 8),
            nn.ReLU(True),

            nn.ConvTranspose2d(dim * 8, dim * 4, 4, 2, 1),
            nn.BatchNorm2d(dim * 4),
            nn.ReLU(True),

            nn.ConvTranspose2d(dim * 4, dim * 2, 4, 2, 1),
            nn.BatchNorm2d(dim * 2),
            nn.ReLU(True),

            nn.ConvTranspose2d(dim * 2, dim, 4, 2, 1),
            nn.BatchNorm2d(dim),
            nn.ReLU(True),

            nn.ConvTranspose2d(dim, input_dim, 4, 2, 1),
            nn.Tanh()
        )
        # self.encoder = nn.Sequential(
        #     nn.Conv2d(input_dim, dim, 4, 2, 1),
        #     nn.BatchNorm2d(dim),
        #     nn.ReLU(True),
        #     nn.Conv2d(dim, dim, 4, 2, 1),
        #     nn.BatchNorm2d(dim),
        #     nn.ReLU(True),
        #     nn.Conv2d(dim, dim, 5, 1, 0),
        #     nn.BatchNorm2d(dim),
        #     nn.ReLU(True),
        #     nn.Conv2d(dim, z_dim * 2, 3, 1, 0),
        #     nn.BatchNorm2d(z_dim * 2)
        # )
        #
        # self.decoder = nn.Sequential(
        #     nn.ConvTranspose2d(z_dim, dim, 3, 1, 0),
        #     nn.BatchNorm2d(dim),
        #     nn.ReLU(True),
        #     nn.ConvTranspose2d(dim, dim, 5, 1, 0),
        #     nn.BatchNorm2d(dim),
        #     nn.ReLU(True),
        #     nn.ConvTranspose2d(dim, dim, 4, 2, 1),
        #     nn.BatchNorm2d(dim),
        #     nn.ReLU(True),
        #     nn.ConvTranspose2d(dim, input_dim, 4, 2, 1),
        #     nn.Tanh()
        # )

        self.apply(weights_init)

    def forward(self, x):
        mu, logvar = self.encoder(x).chunk(2, dim=1)

        q_z_x = Normal(mu, logvar.mul(.5).exp())
        p_z = Normal(torch.zeros_like(mu), torch.ones_like(logvar))
        kl_div = kl_divergence(q_z_x, p_z).sum(1).mean()

        x_tilde = self.decoder(q_z_x.rsample())
        return x_tilde, kl_div

    def encode(self, x):
        mean, logvar = self.encoder(x).chunk(2, dim=1)
        return torch.flatten(mean, start_dim=1), torch.flatten(logvar, start_dim=1)

    def decode(self, z):
        z = torch.reshape(z,(len(z), self.z_dim, 2, 2))
        samples = self.decoder(z)
        return samples

    def reconstruction_loss(self, x_reconstructed, x):
        return F.mse_loss(x_reconstructed, x, size_average=False) / x.size(0)

    def kl_divergence_loss(self, mean, logvar):
        return torch.mean(-0.5 * torch.sum(1 + logvar - mean ** 2 - logvar.exp(), dim = (1,2,3)), dim = 0)

    def loss_function(self,
                      *args,
                      **kwargs):
        """
        Computes the VAE loss function.
        KL(N(\mu, \sigma), N(0, 1)) = \log \frac{1}{\sigma} + \frac{\sigma^2 + \mu^2}{2} - \frac{1}{2}
        :param args:
        :param kwargs:
        :return:
        """
        # self.num_iter += 1
        recons = args[0]
        input = args[1]
        mu = args[2]
        log_var = args[3]

        kld_weight = kwargs['M_N']

        recons_loss = self.reconstruction_loss(recons,input)

        kld_loss = self.kl_divergence_loss(mu, log_var)

        total_loss = recons_loss + kld_weight * kld_loss
        
        return {'total_loss': total_loss, 'Reconstruction_Loss':recons_loss, 'KLD':kld_loss}

    # =====
    # Utils
    # =====

    @property
    def name(self):
        return (
            'VAE'
            '-{kernel_num}k'
            '-{label}'
            '-{channel_num}x{image_size}x{image_size}'
        ).format(
            label=self.label,
            kernel_num=self.z_dim,
            image_size=self.image_size,
            channel_num=self.input_dim,
        )

    def sample(self, num_samples, cuda):
        """
        Samples from the latent space and return the corresponding
        image space map.
        :param num_samples: (Int) Number of samples
        :param current_device: (Int) Device to run the model
        :return: (Tensor)
        """
        z = torch.randn(num_samples,
                        self.z_dim,2,2)

        if cuda:
            z = z.to('cuda')


        samples = self.decoder(z)
        return torch.flatten(z, start_dim=1), samples


    def generate(self, x):
        """
        Given an input image x, returns the reconstructed image
        :param x: (Tensor) [B x C x H x W]
        :return: (Tensor) [B x C x H x W]
        """

        return self.forward(x)[0]

    def _is_on_cuda(self):
        return next(self.parameters()).is_cuda

    def generate_reconstructions(self, data_loader, save_dir=None, device="cpu"):

        if save_dir is None:
            save_dir = os.path.join("Results", "vae")
        os.makedirs(save_dir, exist_ok=True)
        root_path_split = data_loader.dataset.root.split("/")
        dataset_name = root_path_split[root_path_split.index("Dataset")+1]

        self.eval()
        data = next(iter(data_loader))
        x = data[0]
        x = x[:4].to(device)
        x_tilde, kl_div = self(x)
        x_cat = torch.cat([x, x_tilde], 0)
        images = (x_cat.cpu().data + 1) / 2

        save_image(
            images,
            os.path.join(save_dir, 'vae_reconstructions_{}.png'.format(dataset_name)),
            nrow=4
        )


def load_vae(input_dim, hidden_dim, z_dim, weight_path=None, device="cpu"):
    # load VAE model
    vae = VAE(input_dim, hidden_dim, z_dim)
    vae = vae.to(device)
    if weight_path is not None: 
        assert os.path.exists(weight_path), f"File not found: {weight_path}"
        vae.load_state_dict(torch.load(weight_path, map_location=device))
    return vae