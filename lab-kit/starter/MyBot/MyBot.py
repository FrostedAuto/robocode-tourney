from robocode_tank_royale.bot_api.bot import Bot
from robocode_tank_royale.bot_api.color import Color
from robocode_tank_royale.bot_api.events import ScannedBotEvent, HitByBulletEvent, HitWallEvent


# ------------------------------------------------------------------
# MyBot - starter bot for the club tournament (based on MyFirstBot).
#
# BEFORE YOU SUBMIT, give it your own name. Three things must match:
#   1. the class name below          class RedBaron(Bot):
#   2. this file's name              RedBaron.py
#   3. the .json file's name         RedBaron.json
# (and the folder name, if you zip the folder). Letters, digits and _ only.
# Also change it in main() at the bottom.
#
# Ideas to make it better: aim where the enemy is going, not where it is;
# fire harder when the enemy is close; keep moving so you are hard to hit.
# ------------------------------------------------------------------
class MyBot(Bot):
    def run(self) -> None:
        """Called at the start of every round."""
        self.body_color = Color.from_rgb(0x2A, 0x9D, 0x8F)
        self.turret_color = Color.from_rgb(0xE9, 0xC4, 0x6A)
        self.radar_color = Color.from_rgb(0xF4, 0xA2, 0x61)

        while self.running:
            self.forward(100)
            self.turn_gun_left(360)
            self.back(100)
            self.turn_gun_left(360)

    def on_scanned_bot(self, e: ScannedBotEvent) -> None:
        """We saw another bot: fire. Closer = stronger shot."""
        distance = self.distance_to(e.x, e.y)
        self.fire(3 if distance < 200 else 1)

    def on_hit_by_bullet(self, e: HitByBulletEvent) -> None:
        """We were hit: turn sideways to the bullet so the next one misses."""
        bearing = self.calc_bearing(e.bullet.direction)
        self.turn_right(90 - bearing)

    def on_hit_wall(self, e: HitWallEvent) -> None:
        """Bounced into a wall: back off."""
        self.back(50)


def main() -> None:
    MyBot().start()


if __name__ == "__main__":
    main()
