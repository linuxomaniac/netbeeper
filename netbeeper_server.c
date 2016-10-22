/*
 * netbeeper_server : serveur qui va de pair avec netbeeper.py. Le serveur est chargé de recevoir les notes que parse netbeeper.py et de les jouer. Nécessite un acces à /dev/tty0 (utilisateur dans le groupe tty)
 * Compilation : gcc netbeeper_server.c -Wall -c=std11 -lpthread -o netbeeper_server
 * Écrit par Linuxomaniac, sous licence GPLv3
 */

#define PORT 4242
#define DELAY_CORRECTION - 0.13// Correction empirique du délai

#define _XOPEN_SOURCE 700// Sinon warning : nanosleep implicit declaration

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/kd.h>
#include <arpa/inet.h>
#include <pthread.h>
#include <sys/time.h>
#include <ifaddrs.h>

#ifndef CLOCK_TICK_RATE
#define CLOCK_TICK_RATE 1193180
#endif

#define PAQUET_AREUREADY 1
#define PAQUET_OKREADY 2
#define PAQUET_NOTE 3
#define PAQUET_EOF 4
#define PAQUET_START 5
#define PAQUET_OKSTART 6
#define PAQUET_FINISHED 7

typedef struct beep_params {
	unsigned int freq;
	unsigned int length;
	unsigned int delay;
	struct beep_params *next;
} beep_params;

struct thread_args {
	beep_params *params;
	int sock;
	int serversock;
};

typedef struct paquet {
	unsigned char status;
	unsigned int data1;
	unsigned int data2;
	unsigned int data3;
} paquet;

// Global, pas top, cependant il faut que la fonction handle_signal() puisse y accéder
int console_fd = -1;

int recv_exact(int sock, paquet *out_buf, unsigned int size) {
	int n;
	unsigned int bytes_to_get = size, copied_so_far = 0;
	char raw_buf[size];

	while((n = recv(sock, raw_buf, bytes_to_get, 0)) > 0) {
		memcpy(out_buf + copied_so_far, raw_buf, n);
		copied_so_far += n;
		bytes_to_get -= n;

		if(bytes_to_get == 0) {
			break;
		}
	}

	if(n > 0) {
		n = size;
	}

	return n;
}

// Un petit truc pour sleep précisément
void msleep(double milisec) {
	struct timespec req;
	req.tv_sec = (int)(milisec / 1000);
	req.tv_nsec = (milisec - req.tv_sec * 1000) * 1000000;
	nanosleep(&req, NULL);
}

void beep(unsigned int freq) {
	if(ioctl(console_fd, KIOCSOUND, freq != 0 ? (int)(CLOCK_TICK_RATE/freq) : freq) < 0) {
		perror("ioctl");
	}
}

// Si on interrompt le programme, on arrête le son
void handle_signal(int signum) {
	if(signum == SIGINT) {
		if(console_fd >= 0) {
			beep(0);// Plus de son
			close(console_fd);
		}
		exit(signum);// On quitte pépère
	}
}

void do_beep(unsigned int freq, double length) {
	beep(freq);// Beep
	msleep(length - 0.0871);// On attend la durée de la longueur de la note (on soustrait la durée de l'appel à IOCTL)
	beep(0);// Stop beep
}

void print_ips(void) {
	struct ifaddrs *addrs, *tmp;
	struct sockaddr_in *pAddr;

	getifaddrs(&addrs);
	tmp = addrs;

	while(tmp) {
		if(tmp->ifa_addr && tmp->ifa_addr->sa_family == AF_INET) {
			pAddr = (struct sockaddr_in *)tmp->ifa_addr;
			printf("%s -> %s\n", tmp->ifa_name, inet_ntoa(pAddr->sin_addr));
		}
		tmp = tmp->ifa_next;
	}

	freeifaddrs(addrs);
}

void *play_beep(void *args) {
	struct thread_args *params = args;
	beep_params *current = params->params;
	int newsock;
	paquet buf = {0};
	struct timeval start, stop;
	double ms_total = 0, ecart;
	unsigned int tours = 0;

	// On ouvre ici le périf de beep pour ne pas l'ouvrir à chaque note.
	if((console_fd = open("/dev/tty0", O_WRONLY)) < 0) {
		printf("Could not open /dev/tty0 for writing.\n");
		perror("Open");
		close(params->serversock);
		exit(7);
	}

	if((newsock = accept(params->serversock, NULL, NULL)) < 0) {// On spawn un socket inutile pour attendre, car la création de thread peut prendre du temps
		close(params->sock);
		close(params->serversock);
		exit(9);
	}

	printf("En attente du signal...");
	if(recv_exact(newsock, &buf, sizeof(buf)) < 0) {
		printf("\nErreur :");
		perror("Recv");
		close(params->sock);
		close(params->serversock);
		exit(10);
	}
	close(newsock);

	printf(" C'est parti ! Un temps d'attente de %d millisecondes avant de commencer...\n", current->delay);

	gettimeofday(&start, NULL);

	while(current->next != NULL) {
		if(current->freq > 0 && current->length > 0) {// Évite des appels inutiles à IOCTL dans le cas où la note est juste un délai
			do_beep(current->freq, current->length + DELAY_CORRECTION);
		}
		tours += 1;
		ms_total += current->length + current->delay;
		msleep(current->delay + DELAY_CORRECTION);
		current = current->next;
	}

	gettimeofday(&stop, NULL);
	ecart = (double)(ms_total - ((double)(stop.tv_usec - start.tv_usec) / 1000 + (double)(stop.tv_sec - start.tv_sec) * 1000));

	printf("Écart total : %f ms.\tÉcart moyen par note : %f ms.\n", ecart, (double)(ecart / tours));

	close(console_fd);
	console_fd = -1;

	buf.status = PAQUET_FINISHED;
	send(params->sock, &buf, sizeof(buf), 0);// On envoie n'importe quoi, comme ça le client en Python va fermer le socket
	// C'est nécessaire de fermer le socket, car sinon, on n'a aucun moyen à partir du thread de dire à recv() qu'on a fini de lire la musique

	return NULL;
}

int main(void) {
	int serversock, newsock, n;
	struct sockaddr_in my_addr;
	unsigned int yes = 1;
	paquet buf;
	beep_params *first, *current, *next;
	struct thread_args params;
	pthread_t thread_id;
	pthread_attr_t attr;

	if((serversock = socket(AF_INET, SOCK_STREAM, 0)) < 0) {
		exit(1);
	}

	my_addr.sin_family = AF_INET;
	my_addr.sin_port = htons(PORT);
	my_addr.sin_addr.s_addr = INADDR_ANY;
	memset(my_addr.sin_zero, 0, sizeof(my_addr.sin_zero));

	if(setsockopt(serversock, SOL_SOCKET, SO_REUSEADDR, (char *)&yes, sizeof(int)) < 0) {
		close(serversock);
		exit(2);
	}

	if(bind(serversock, (struct sockaddr *)&my_addr, sizeof(struct sockaddr)) < 0) {
		close(serversock);
		exit(3);
	}

	if(listen(serversock, 1) < 0) {// Max 1 connexion en attente
		close(serversock);
		exit(4);
	}

	printf("En écoute sur le port tai tai %d, sur les IP suivantes :\n", PORT);
	print_ips();

	signal(SIGINT, handle_signal);

	while(1) {
		yes = 1;
		printf("\nOn attend les connexions...\n");
		if((newsock = accept(serversock, NULL, NULL)) < 0) {
			close(serversock);
			exit(5);
		}

		printf("Une connexion ! En attente de la sauce...");
		if(recv_exact(newsock, &buf, sizeof(paquet)) > 0) {
			if(buf.status == PAQUET_AREUREADY && buf.data1 == 0 && buf.data2 == 0 && buf.data3 == 0) {
				printf(" Okay !\n");

				// On renvoie la réponse
				buf.status = PAQUET_OKREADY;
				// data1, 2 et 3 sont inchangés (ils valent 0)
				send(newsock, &buf, sizeof(paquet), 0);
			} else {
				printf(" Mauvaise réponse !\n");
				close(newsock);
				continue;
			}
		} else {
			printf(" Fausse couche !\n");
			close(newsock);
			continue;
		}

		first = (beep_params *)malloc(sizeof(beep_params));
		current = first;
		current->next = NULL;// En cas d'avortement

		printf("Réception des données...");

		while(1) {
			if((n = recv_exact(newsock, &buf, sizeof(paquet))) > 0) {
				if(buf.status == PAQUET_NOTE && (buf.data1 != 0 || buf.data2 != 0 || buf.data3 != 0)) {
					current->freq = buf.data1;
					current->length = buf.data2;
					current->delay = buf.data3;

					current->next = (beep_params *)malloc(sizeof(beep_params));
					current = current->next;
				} else if(buf.status == PAQUET_EOF && buf.data1 == 0 && buf.data2 == 0 && buf.data3 == 0) {
					break;
				} else {
					printf(" Paquet invalide !\n");
					yes = 0;
					break;
				}
			} else {
				printf(" Connexion avortée !\n");
				yes = 0;
				break;
			}
		}
		current->next = NULL;

		if(yes == 1) {
			printf(" Sauce reçue !\n");

			// On avertit en conséquence le client
			buf.status = PAQUET_START;
			buf.data1 = 0;
			buf.data2 = 0;
			buf.data3 = 0;
			send(newsock, &buf, sizeof(paquet), 0);

			if((n = recv_exact(newsock, &buf, sizeof(paquet))) > 0) {
				if(buf.status == PAQUET_OKSTART && buf.data1 == 0 && buf.data2 == 0 && buf.data3 == 0) {
					printf("Tout le monde est prêt !\n");
				} else {
					printf("Le client n'est pas prêt !\n");
					yes = 0;
				}
			} else {
				printf("La client nous a fait faux-bond !\n");
				yes = 0;
			}

			if(yes == 1) {
				params.params = first;
				params.sock = newsock;
				params.serversock = serversock;

				pthread_attr_init(&attr);
				pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);// Évite quelques erreurs Valgrind
				if(pthread_create(&thread_id, &attr, play_beep, &params) != 0) {
					close(newsock);
					close(serversock);
					exit(6);
				}

				while((n = recv_exact(newsock, &buf, sizeof(paquet))) > 0) {
					// Tant qu'on reçoit des données, on les jette
				}
			}
		}

		if(n <= 0) {
			if(yes == 1) {// Si la connexion a été avortée, le thread n'a pas été lancé
				pthread_cancel(thread_id);
			}
			printf("Connexion fermée.\n");
			if(console_fd >= 0)
			{
				beep(0);// Stop
				close(console_fd);
				console_fd = -1;
			}
		}

		current = first;
		while(current->next != NULL) {// On free tout ici, car si on kill le processus, on ne pourra pas finir la désallocation en toute impunité
			next = current->next;
			free(current);
			current = next;
		}
		free(current);

		close(newsock);
	}
	close(serversock);

	return 0;
}
