import pygame
import sys
import time
import random

pygame.init()

SCREEN_WIDTH = 600
SCREEN_HEIGHT = 400
GRID_SIZE = 20
FPS = 10
WIN_LENGTH = 10

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREEN = (0, 255, 0)
RED = (255, 0, 0)

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption('Snake')

def draw_grid():
    for x in range(0, SCREEN_WIDTH, GRID_SIZE):
        pygame.draw.line(screen, BLACK, (x, 0), (x, SCREEN_HEIGHT))
    for y in range(0, SCREEN_HEIGHT, GRID_SIZE):
        pygame.draw.line(screen, BLACK, (0, y), (SCREEN_WIDTH, y))

def create_apple():
    apple_x = random.randint(0, (SCREEN_WIDTH - GRID_SIZE) // GRID_SIZE) * GRID_SIZE
    apple_y = random.randint(0, (SCREEN_HEIGHT - GRID_SIZE) // GRID_SIZE) * GRID_SIZE
    return apple_x, apple_y

def draw_text(text, font, color, x, y):
    text_surface = font.render(text, True, color)
    text_rect = text_surface.get_rect()
    text_rect.center = (x, y)
    screen.blit(text_surface, text_rect)

def main():
    snake = [(100, 100)]
    direction = 'RIGHT'
    apple = create_apple()
    score = 0
    start_time = time.time()

    while True:
        keys = pygame.key.get_pressed()
        if keys[pygame.K_ESCAPE]:  # If Escape is pressed, toggle the menu state
            menu_state = not menu_state
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP] and direction != 'DOWN':
            direction = 'UP'
        elif keys[pygame.K_DOWN] and direction != 'UP':
            direction = 'DOWN'
        elif keys[pygame.K_LEFT] and direction != 'RIGHT':
            direction = 'LEFT'
        elif keys[pygame.K_RIGHT] and direction != 'LEFT':
            direction = 'RIGHT'

        head_x, head_y = snake[0]
        if direction == 'UP':
            head_y -= GRID_SIZE
        elif direction == 'DOWN':
            head_y += GRID_SIZE
        elif direction == 'LEFT':
            head_x -= GRID_SIZE
        elif direction == 'RIGHT':
            head_x += GRID_SIZE

        if head_x < 0 or head_x >= SCREEN_WIDTH or head_y < 0 or head_y >= SCREEN_HEIGHT:
            draw_text('Game Over', pygame.font.Font(None, 36), BLACK, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
            pygame.display.flip()
            time.sleep(3)
            pygame.quit()
            sys.exit()

        snake.insert(0, (head_x, head_y))
        if head_x == apple[0] and head_y == apple[1]:
            score += 1
            apple = create_apple()
        else:
            snake.pop()

        screen.fill(WHITE)
        draw_grid()
        pygame.draw.rect(screen, GREEN, (*apple, GRID_SIZE, GRID_SIZE))
        for segment in snake:
            pygame.draw.rect(screen, RED, (*segment, GRID_SIZE, GRID_SIZE))

        if len(snake) >= WIN_LENGTH:
            draw_text('You Win!', pygame.font.Font(None, 36), BLACK, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
            pygame.display.flip()
            time.sleep(3)
            pygame.quit()
            sys.exit()

        if time.time() - start_time > 180:
            draw_text('Game Over', pygame.font.Font(None, 36), BLACK, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
            pygame.display.flip()
            time.sleep(3)
            pygame.quit()
            sys.exit()

        pygame.display.flip()
        pygame.time.Clock().tick(FPS)

if __name__ == '__main__':
    main()