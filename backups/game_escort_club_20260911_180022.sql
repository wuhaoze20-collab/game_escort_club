-- MySQL dump 10.13  Distrib 8.2.0, for Win64 (x86_64)
--
-- Host: localhost    Database: game_escort_club
-- ------------------------------------------------------
-- Server version	8.2.0

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `boss_info`
--

DROP TABLE IF EXISTS `boss_info`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `boss_info` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `consume_amount` int DEFAULT NULL,
  `balance` int DEFAULT NULL,
  `order_count` int DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_boss_info_username` (`username`),
  KEY `ix_boss_info_id` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `boss_info`
--

LOCK TABLES `boss_info` WRITE;
/*!40000 ALTER TABLE `boss_info` DISABLE KEYS */;
INSERT INTO `boss_info` VALUES (1,'laoban',635000,4955,47,'2026-09-10 13:47:22'),(2,'laoban_02',423100,4306,28,'2026-09-10 13:47:22'),(3,'laoban_03',1006000,5896,73,'2026-09-10 13:47:22');
/*!40000 ALTER TABLE `boss_info` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `content_config`
--

DROP TABLE IF EXISTS `content_config`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `content_config` (
  `id` int NOT NULL AUTO_INCREMENT,
  `config_key` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `config_value` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_content_config_config_key` (`config_key`),
  KEY `ix_content_config_id` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `content_config`
--

LOCK TABLES `content_config` WRITE;
/*!40000 ALTER TABLE `content_config` DISABLE KEYS */;
INSERT INTO `content_config` VALUES (1,'notice','{\"title\": \"欢迎来到大狗嚼电竞\", \"content\": \"「大狗嚼电竞」专注游戏陪玩、护航、上分服务，平台打手全部实名认证、分级管理（娱乐陪/技术陪），服务全程可评价可投诉。\\n\\n【服务时间】\\n全天 24 小时在线接单，高峰期（18:00-24:00）打手充足，下单后 5 分钟内响应。\\n\\n【平台活动】\\n· 新用户首单立减 20%；\\n· 充值满 100 送 10 大狗币，满 300 送 50，满 500 送 120，满 1000 送 300；\\n· 充值可叠加会员专属福利，充得越多送得越多。\\n\\n【温馨提示】\\n· 请通过平台内下单，切勿私下转账，谨防上当受骗；\\n· 大狗币充值与消费全程受平台保障；\\n· 遇到任何问题请联系在线客服。\\n\\n愿你在每一局游戏里，都能畅快到底！\", \"updateTime\": \"2026-09-11 18:00\"}','2026-09-11 17:48:59'),(2,'orderGuide','[\"下单前请先在「价格预览」查看各游戏与业务的单价\", \"进入「点单中心」选择游戏、业务类型、打手与时长，金额由系统自动计算\", \"下单时可填写备注（段位、模式、上分要求等），打手将根据备注决定接单或拒单\", \"打手接单并开始服务后，服务完成由打手提交结单，老板确认后费用才转入打手后台\", \"点单消耗大狗币（1元 = 1大狗币），金额按单价×时长/数量自动计算，不可手动修改\", \"结单后可自愿打赏打手，单次打赏上限不超过订单单价的 30%\", \"打手提现需满足 30 天冷却期，金额转入绑定的收款账户\", \"打手简介、标签、等级全部公开透明，老板可自行筛选\", \"服务结束后 3 天内未评价的订单自动默认为好评\", \"老板可对不满意的订单发起投诉，打手可申诉，由管理员最终审核\", \"打手接单后长时间未开始服务，老板可申请取消订单并退款\", \"请勿绕过平台私下交易，私下交易产生的纠纷平台不予受理\", \"请文明沟通，恶意辱骂、骚扰将被处罚，情节严重将封禁账号\", \"账号被拉黑后，后台金额将转入公司账户\", \"如有疑问请联系在线客服\"]','2026-09-11 17:48:59'),(3,'price','[{\"game\": \"王者荣耀\", \"rank\": \"青铜-钻石\", \"price\": 25, \"unit\": \"元/小时\"}, {\"game\": \"王者荣耀\", \"rank\": \"钻石-王者\", \"price\": 40, \"unit\": \"元/小时\"}, {\"game\": \"英雄联盟\", \"rank\": \"青铜-铂金\", \"price\": 30, \"unit\": \"元/小时\"}, {\"game\": \"英雄联盟\", \"rank\": \"铂金-钻石\", \"price\": 50, \"unit\": \"元/小时\"}, {\"game\": \"和平精英\", \"rank\": \"青铜-王牌\", \"price\": 35, \"unit\": \"元/小时\"}, {\"game\": \"原神\", \"rank\": \"深渊代打\", \"price\": 60, \"unit\": \"元/层\"}, {\"game\": \"三角洲行动\", \"rank\": \"陪玩护航\", \"price\": 35, \"unit\": \"元/小时\"}, {\"game\": \"三角洲行动\", \"rank\": \"跑刀摸金\", \"price\": 28, \"unit\": \"元/小时\"}, {\"game\": \"三角洲行动\", \"rank\": \"战术配合\", \"price\": 45, \"unit\": \"元/小时\"}, {\"game\": \"Apex英雄\", \"rank\": \"陪玩上分\", \"price\": 35, \"unit\": \"元/小时\"}, {\"game\": \"Apex英雄\", \"rank\": \"排位上分\", \"price\": 45, \"unit\": \"元/小时\"}, {\"game\": \"Apex英雄\", \"rank\": \"通行证代肝\", \"price\": 1.5, \"unit\": \"元/级\"}, {\"game\": \"Apex英雄\", \"rank\": \"通行证满级\", \"price\": 70, \"unit\": \"元/满级\"}, {\"game\": \"无畏契约\", \"rank\": \"陪玩娱乐\", \"price\": 35, \"unit\": \"元/小时\"}, {\"game\": \"无畏契约\", \"rank\": \"排位上分\", \"price\": 50, \"unit\": \"元/小时\"}, {\"game\": \"CS2\", \"rank\": \"陪玩娱乐\", \"price\": 30, \"unit\": \"元/小时\"}, {\"game\": \"CS2\", \"rank\": \"排位上分\", \"price\": 45, \"unit\": \"元/小时\"}]','2026-09-11 15:13:22'),(4,'recharge','[{\"amount\": 100, \"gift\": 10, \"bonus\": \"送大狗币10枚 + 普通会员1天\"}, {\"amount\": 300, \"gift\": 50, \"bonus\": \"送大狗币50枚 + 白银会员7天\"}, {\"amount\": 500, \"gift\": 120, \"bonus\": \"送大狗币120枚 + 黄金会员15天\"}, {\"amount\": 1000, \"gift\": 300, \"bonus\": \"送大狗币300枚 + 黄金会员30天 + 专属打手\"}, {\"amount\": 2000, \"gift\": 800, \"bonus\": \"送大狗币800枚 + 黄金会员60天 + 专属打手\"}, {\"amount\": 5000, \"gift\": 1500, \"bonus\": \"送大狗币1500枚 + 钻石会员30天 + 专属打手+ 专属客服\"}, {\"amount\": 10000, \"gift\": 3500, \"bonus\": \"送大狗币3500枚 + 钻石会员60天 + 专属打手送大狗币1500枚 + 钻石会员30天 + 专属打手+ 专属24小时客服\"}]','2026-09-11 15:18:12'),(5,'member','[{\"level\": \"普通会员\", \"discount\": \"无折扣\", \"benefits\": \"基础客服服务、订单优先分配\"}, {\"level\": \"白银会员\", \"discount\": \"95折\", \"benefits\": \"专属客服、订单优先派单、生日福利\"}, {\"level\": \"黄金会员\", \"discount\": \"88折\", \"benefits\": \"专属客服、指定打手、免费改单、生日福利\"}, {\"level\": \"钻石会员\", \"discount\": \"8折\", \"benefits\": \"一对一专属客服、顶级打手优先、全程保段、退款优先\"}]','2026-09-10 13:47:22'),(6,'payment','[{\"name\": \"微信支付\", \"desc\": \"支持微信扫码支付，实时到账\", \"icon\": \"💬\"}, {\"name\": \"支付宝\", \"desc\": \"支持支付宝扫码支付，实时到账\", \"icon\": \"💰\"}, {\"name\": \"QQ钱包\", \"desc\": \"支持QQ钱包支付，即时到账\", \"icon\": \"🐧\"}, {\"name\": \"银行卡转账\", \"desc\": \"支持主流银行卡转账，1-2小时到账\", \"icon\": \"💳\"}]','2026-09-10 13:47:22'),(7,'punishment','[{\"level\": \"警告\", \"desc\": \"轻微违规（言语不当、消极服务等），累计3次升级为停单处罚\", \"date\": \"2026-09-01\"}, {\"level\": \"停单3天\", \"desc\": \"中度违规（无故拒单、态度恶劣），期间无法接单\", \"date\": \"2026-09-01\"}, {\"level\": \"封禁账号\", \"desc\": \"严重违规（作弊、诈骗、恶意刷单等），永久封禁并扣除后台金额\", \"date\": \"2026-09-01\"}]','2026-09-11 16:17:03'),(8,'matches','[{\"game\": \"三角洲行动\", \"title\": \"三角洲行动官方赛事直播\", \"url\": \"https://live.bilibili.com/1921272912\"}, {\"game\": \"Apex英雄\", \"title\": \"Apex英雄官方赛事直播\", \"url\": \"https://space.bilibili.com/1676940341\"}, {\"game\": \"CS2\", \"title\": \"CS2官方赛事直播\", \"url\": \"https://space.bilibili.com/474595627\"}, {\"game\": \"英雄联盟\", \"title\": \"英雄联盟官方赛事直播\", \"url\": \"https://live.bilibili.com/6\"}, {\"game\": \"无畏契约\", \"title\": \"无畏契约官方赛事直播\", \"url\": \"https://live.bilibili.com/22908869/?live_from=86001&spm_id_from=333.1387.0.0\"}, {\"game\": \"刀塔2\", \"title\": \"刀塔2官方赛事直播\", \"url\": \"https://space.bilibili.com/17561885\"}, {\"game\": \"王者荣耀\", \"title\": \"王者荣耀官方赛事直播\", \"url\": \"https://live.bilibili.com/55\"}]','2026-09-11 17:01:22'),(9,'company_balance','{\"balance\": 0}','2026-09-11 16:18:19'),(10,'company_records','[]','2026-09-11 16:17:03');
/*!40000 ALTER TABLE `content_config` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `notifications`
--

DROP TABLE IF EXISTS `notifications`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `notifications` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `title` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content` text COLLATE utf8mb4_unicode_ci,
  `type` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_read` int DEFAULT NULL,
  `link` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_notifications_id` (`id`),
  KEY `ix_notifications_user_id` (`user_id`),
  CONSTRAINT `notifications_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `notifications`
--

LOCK TABLES `notifications` WRITE;
/*!40000 ALTER TABLE `notifications` DISABLE KEYS */;
INSERT INTO `notifications` VALUES (2,2,'新订单待派单','有新的待派单订单 ORD20260911152431AD4D，请及时派单','info',1,'/order','2026-09-11 15:24:31'),(3,2,'新订单待派单','有新的待派单订单 ORD202609111533079533，请及时派单','info',1,'/order','2026-09-11 15:33:07'),(4,3,'派单成功','客服已为您派单：打手 软糖，订单 ORD202609111533079533，等待开始服务','success',1,'/order','2026-09-11 15:33:29'),(5,17,'新订单','您有新的派单订单 ORD202609111533079533，请及时接单','info',0,'/order','2026-09-11 15:33:29');
/*!40000 ALTER TABLE `notifications` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `orders`
--

DROP TABLE IF EXISTS `orders`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `orders` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_no` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `boss_username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `player_username` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `game_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `duration_min` int NOT NULL,
  `total_amount` int NOT NULL,
  `remark` text COLLATE utf8mb4_unicode_ci,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `start_time` datetime DEFAULT NULL,
  `end_time` datetime DEFAULT NULL,
  `service_note` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_orders_order_no` (`order_no`),
  KEY `ix_orders_id` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=38 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `orders`
--

LOCK TABLES `orders` WRITE;
/*!40000 ALTER TABLE `orders` DISABLE KEYS */;
INSERT INTO `orders` VALUES (2,'GC20260910135516001','laoban','dashou_09','王者荣耀',240,15400,'尽量拿MVP','completed','2026-08-31 13:55:17','2026-08-31 14:01:17','2026-08-31 18:01:17',''),(3,'GC20260910135516002','laoban','dashou_09','CS2',240,7300,'老板想上分，稳一点','completed','2026-08-15 13:55:17','2026-08-15 13:58:17','2026-08-15 17:58:17',''),(4,'GC20260910135516003','laoban','dashou_09','英雄联盟',90,16400,'别浪，稳赢','completed','2026-07-28 13:55:17','2026-07-28 14:06:17','2026-07-28 15:36:17',''),(5,'GC20260910135516004','laoban','dashou_11','英雄联盟',60,12800,'别浪，稳赢','completed','2026-08-01 13:55:17','2026-08-01 14:10:17','2026-08-01 15:10:17',''),(6,'GC20260910135516005','laoban','dashou_08','CS2',180,8700,'陪练新赛季冲分','completed','2026-08-21 13:55:17','2026-08-21 14:02:17','2026-08-21 17:02:17',''),(7,'GC20260910135516006','laoban','dashou_08','英雄联盟',120,7100,'尽量拿MVP','completed','2026-08-07 13:55:17','2026-08-07 13:58:17','2026-08-07 15:58:17',''),(8,'GC20260910135516007','laoban','dashou_10','英雄联盟',90,9100,'多交流，教学局','completed','2026-08-01 13:55:17','2026-08-01 14:07:17','2026-08-01 15:37:17',''),(9,'GC20260910135516008','laoban','dashou','王者荣耀',150,10600,'别浪，稳赢','completed','2026-08-30 13:55:17','2026-08-30 14:05:17','2026-08-30 16:35:17',''),(10,'GC20260910135516009','laoban','dashou_05','CS2',60,20000,'尽量拿MVP','completed','2026-08-21 13:55:17','2026-08-21 14:08:17','2026-08-21 15:08:17',''),(11,'GC20260910135516010','laoban','dashou','原神',90,7600,'','completed','2026-08-23 13:55:17','2026-08-23 14:05:17','2026-08-23 15:35:17',''),(12,'GC20260910135516011','laoban','dashou_06','英雄联盟',120,4300,'','processing','2026-07-31 13:55:17','2026-07-31 14:04:17',NULL,''),(13,'GC20260910135516012','laoban_02','dashou_11','和平精英',150,12400,'多交流，教学局','completed','2026-08-14 13:55:17','2026-08-14 14:08:17','2026-08-14 16:38:17',''),(14,'GC20260910135516013','laoban_02','dashou_11','CS2',90,11100,'','completed','2026-08-03 13:55:17','2026-08-03 14:04:17','2026-08-03 15:34:17',''),(15,'GC20260910135516014','laoban_02','dashou_04','王者荣耀',150,12500,'','completed','2026-08-01 13:55:17','2026-08-01 14:05:17','2026-08-01 16:35:17',''),(16,'GC20260910135516015','laoban_02','dashou_03','英雄联盟',120,10000,'陪练新赛季冲分','completed','2026-08-15 13:55:17','2026-08-15 14:09:17','2026-08-15 16:09:17',''),(17,'GC20260910135516016','laoban_02','dashou','王者荣耀',180,7700,'','completed','2026-09-03 13:55:17','2026-09-03 14:04:17','2026-09-03 17:04:17',''),(18,'GC20260910135516017','laoban_02','dashou_06','王者荣耀',240,4700,'陪练新赛季冲分','completed','2026-09-05 13:55:17','2026-09-05 14:10:17','2026-09-05 18:10:17',''),(19,'GC20260910135516018','laoban_02','dashou_02','王者荣耀',150,12300,'','completed','2026-07-28 13:55:17','2026-07-28 14:03:17','2026-07-28 16:33:17',''),(20,'GC20260910135516019','laoban_02','dashou_05','CS2',180,18000,'','completed','2026-08-07 13:55:17','2026-08-07 14:04:17','2026-08-07 17:04:17',''),(21,'GC20260910135516020','laoban_02','dashou_02','和平精英',150,6100,'语音沟通','completed','2026-09-02 13:55:17','2026-09-02 14:05:17','2026-09-02 16:35:17',''),(22,'GC20260910135516021','laoban_02','dashou_06','英雄联盟',120,18300,'语音沟通','completed','2026-09-04 13:55:17','2026-09-04 14:08:17','2026-09-04 16:08:17',''),(23,'GC20260910135516022','laoban_03','dashou_10','原神',90,6000,'多交流，教学局','pending_settlement','2026-08-09 13:55:17','2026-08-09 14:03:17',NULL,''),(24,'GC20260910135516023','laoban_03','dashou_03','CS2',180,6700,'别浪，稳赢','completed','2026-09-08 13:55:17','2026-09-08 14:02:17','2026-09-08 17:02:17',''),(25,'GC20260910135516024','laoban_03','dashou_02','CS2',90,14900,'','completed','2026-08-21 13:55:17','2026-08-21 14:02:17','2026-08-21 15:32:17',''),(26,'GC20260910135516025','laoban_03','dashou_11','英雄联盟',120,17700,'速战速决','completed','2026-08-24 13:55:17','2026-08-24 14:01:17','2026-08-24 16:01:17',''),(27,'GC20260910135516026','laoban_03','dashou_08','王者荣耀',150,3100,'','completed','2026-08-24 13:55:17','2026-08-24 14:07:17','2026-08-24 16:37:17',''),(28,'GC20260910135516027','laoban_03','dashou_09','CS2',60,18100,'尽量拿MVP','assigned','2026-09-07 13:55:17','2026-09-07 14:00:17',NULL,''),(29,'GC20260910135516028','laoban_03','dashou_08','英雄联盟',90,16500,'陪练新赛季冲分','completed','2026-08-20 13:55:17','2026-08-20 13:58:17','2026-08-20 15:28:17',''),(30,'GC20260910135516029','laoban_03','dashou_03','原神',240,10400,'尽量拿MVP','completed','2026-08-12 13:55:17','2026-08-12 14:00:17','2026-08-12 18:00:17',''),(31,'GC20260910135516030','laoban_03','dashou_08','英雄联盟',180,15500,'','completed','2026-08-12 13:55:17','2026-08-12 14:01:17','2026-08-12 17:01:17',''),(32,'GC20260910135516031','laoban_03','dashou_05','原神',180,18700,'速战速决','completed','2026-09-01 13:55:17','2026-09-01 14:02:17','2026-09-01 17:02:17',''),(33,'GC20260910135516032','laoban_03','dashou_04','CS2',240,12500,'老板想上分，稳一点','completed','2026-08-24 13:55:17','2026-08-24 13:59:17','2026-08-24 17:59:17',''),(35,'ORD202609111452373B7F','laoban','dashou_10','王者荣耀',60,2500,'','pending_accept','2026-09-11 14:52:38',NULL,NULL,''),(37,'ORD202609111533079533','laoban','dashou_12','Apex英雄-通行证代肝',1,7000,'','assigned','2026-09-11 15:33:07',NULL,NULL,'60级');
/*!40000 ALTER TABLE `orders` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `player_info`
--

DROP TABLE IF EXISTS `player_info`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `player_info` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `order_count` int DEFAULT NULL,
  `complaint_count` int DEFAULT NULL,
  `good_rate` float DEFAULT NULL,
  `backend_amount` int DEFAULT NULL,
  `intro` text COLLATE utf8mb4_unicode_ci,
  `level_type` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `tech_level` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_player_info_username` (`username`),
  KEY `ix_player_info_id` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `player_info`
--

LOCK TABLES `player_info` WRITE;
/*!40000 ALTER TABLE `player_info` DISABLE KEYS */;
INSERT INTO `player_info` VALUES (1,'dashou',131,3,66.7,386130,'大家好，我是打手小达，主玩王者荣耀、和平精英，擅长上分护航，王者100星以上，服务耐心，欢迎老板点单！','技术陪','魔王护','2026-09-10 13:47:22'),(2,'dashou_02',98,1,100,308310,'英雄联盟大师段位，主玩打野位，可以语音沟通，稳扎稳打不浪，陪你上分到天亮。','技术陪','211','2026-09-10 13:47:22'),(3,'dashou_03',213,7,100,640305,'全能型打手，王者/联盟/原神都可接单，多年护航经验，口碑老店，品质保障。','娱乐陪','','2026-09-10 13:47:22'),(4,'dashou_04',78,0,NULL,122457,'王者荣耀国服百星打野，985技术陪全程语音指导，稳上分不炸车，高端局也能带飞。','技术陪','985','2026-09-10 13:47:22'),(5,'dashou_05',57,2,NULL,141090,'大专技术陪，主玩王者/和平精英，价格实惠服务到位，性价比之选，欢迎新老板体验。','技术陪','大专','2026-09-10 13:47:22'),(6,'dashou_06',170,4,100,468100,'明星级护航，原神满命深渊、王者巅峰赛顶级对局，高端局专属陪玩，全天可约。','技术陪','明星护','2026-09-10 13:47:22'),(7,'dashou_07',0,0,NULL,0,'985名校技术陪，王者荣耀国服前百打野，意识教学型陪玩，带你上分更带你理解游戏。','技术陪','985','2026-09-10 13:55:18'),(8,'dashou_08',5,0,100,36198,'211技术陪，主玩和平精英，四排带队冲分，战术清晰执行力强，稳定吃鸡。','技术陪','211','2026-09-10 13:55:18'),(9,'dashou_09',3,0,100,28465,'大专技术陪，英雄联盟峡谷之巅选手，主玩中单，价格实惠质量在线。','技术陪','大专','2026-09-10 13:55:18'),(10,'dashou_10',1,0,100,6370,'魔王护专属护航，高端局代练出身，节奏把控一流，全程语音护驾。','技术陪','魔王护','2026-09-10 13:55:18'),(11,'dashou_11',4,0,50,42030,'明星级护航，原神满命深渊速通、王者巅峰赛顶级对局，服务高端客户。','技术陪','明星护','2026-09-10 13:55:18'),(12,'dashou_12',0,0,NULL,0,'娱乐陪玩，能聊能玩会哄人，排位不掉星，输了算我的，开心最重要！','娱乐陪','','2026-09-10 13:55:18');
/*!40000 ALTER TABLE `player_info` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `player_ratings`
--

DROP TABLE IF EXISTS `player_ratings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `player_ratings` (
  `id` int NOT NULL AUTO_INCREMENT,
  `player_username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `boss_username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `order_id` int NOT NULL,
  `rating` int NOT NULL,
  `comment` text COLLATE utf8mb4_unicode_ci,
  `reply` text COLLATE utf8mb4_unicode_ci,
  `reply_time` datetime DEFAULT NULL,
  `review_status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `review_reason` text COLLATE utf8mb4_unicode_ci,
  `review_note` text COLLATE utf8mb4_unicode_ci,
  `review_time` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `order_id` (`order_id`),
  KEY `ix_player_ratings_id` (`id`),
  KEY `ix_player_ratings_player_username` (`player_username`),
  CONSTRAINT `player_ratings_ibfk_1` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=31 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `player_ratings`
--

LOCK TABLES `player_ratings` WRITE;
/*!40000 ALTER TABLE `player_ratings` DISABLE KEYS */;
INSERT INTO `player_ratings` VALUES (1,'dashou_09','laoban',2,1,'【老板投诉】服务中途掉线且态度差（原评价：稳如老狗，一晚上连上三个段，太强了！）','',NULL,'removed','当天网络卡顿但已完成，请求撤销差评','情况属实，撤销差评','2026-09-10 14:19:34','2026-08-31 20:58:17'),(2,'dashou_09','laoban',3,4,'打得挺好，沟通再多一点就更完美了。','',NULL,'normal','','',NULL,'2026-08-15 21:44:17'),(3,'dashou_08','laoban',6,5,'技术一流，配合默契，下次还找你！','感谢支持，你的满意是我最大的动力！','2026-08-23 05:02:17','normal','','',NULL,'2026-08-21 18:32:17'),(4,'dashou_08','laoban',7,5,'全程语音指导，体验拉满，推荐给所有老板！','感谢支持，你的满意是我最大的动力！','2026-08-08 05:58:17','normal','','',NULL,'2026-08-07 16:55:17'),(5,'dashou_10','laoban',8,4,'打得挺好，沟通再多一点就更完美了。','感谢老板认可，下次继续带飞！','2026-08-01 17:37:17','normal','','',NULL,'2026-08-01 17:00:17'),(6,'dashou','laoban',9,5,'全程语音指导，体验拉满，推荐给所有老板！','',NULL,'normal','','',NULL,'2026-08-30 17:57:17'),(7,'dashou','laoban',11,4,'打得挺好，沟通再多一点就更完美了。','',NULL,'normal','','',NULL,'2026-08-23 18:26:17'),(8,'dashou_11','laoban_02',14,3,'还行，偶尔掉线，希望改进。','',NULL,'normal','','',NULL,'2026-08-03 17:33:17'),(9,'dashou_03','laoban_02',16,5,'非常专业，带我上分稳稳的，必须五星！','老板满意就好，随时约我！','2026-08-16 02:09:17','normal','','',NULL,'2026-08-15 19:11:17'),(10,'dashou','laoban_02',17,2,'不太满意，节奏有点慢，再练练吧。','',NULL,'normal','','',NULL,'2026-09-03 17:20:17'),(11,'dashou_06','laoban_02',18,5,'全程语音指导，体验拉满，推荐给所有老板！','',NULL,'normal','','',NULL,'2026-09-05 19:51:17'),(12,'dashou_02','laoban_02',19,5,'技术一流，配合默契，下次还找你！','感谢老板认可，下次继续带飞！','2026-07-30 07:33:17','normal','','',NULL,'2026-07-28 17:07:17'),(13,'dashou_02','laoban_02',21,5,'稳如老狗，一晚上连上三个段，太强了！','',NULL,'normal','','',NULL,'2026-09-02 20:14:17'),(14,'dashou_02','laoban_03',25,5,'技术一流，配合默契，下次还找你！','收到，一定继续保持，感谢五星好评！','2026-08-23 07:32:17','normal','','',NULL,'2026-08-21 19:07:17'),(15,'dashou_11','laoban_03',26,4,'打得挺好，沟通再多一点就更完美了。','',NULL,'normal','','',NULL,'2026-08-24 18:45:17'),(16,'dashou_08','laoban_03',27,4,'质量不错，价格也合理，会回购。','',NULL,'normal','','',NULL,'2026-08-24 16:56:17'),(17,'dashou_08','laoban_03',29,5,'稳如老狗，一晚上连上三个段，太强了！','',NULL,'normal','','',NULL,'2026-08-20 17:39:17'),(18,'dashou_03','laoban_03',30,5,'服务态度超好，有耐心，点赞！','',NULL,'normal','','',NULL,'2026-08-12 21:41:17'),(19,'dashou_09','laoban',4,5,'系统默认好评（结单3天未评价）','',NULL,'normal','','',NULL,'2026-07-31 15:36:17'),(20,'dashou_11','laoban',5,5,'系统默认好评（结单3天未评价）','',NULL,'normal','','',NULL,'2026-08-04 15:10:17'),(21,'dashou_05','laoban',10,5,'系统默认好评（结单3天未评价）','',NULL,'normal','','',NULL,'2026-08-24 15:08:17'),(22,'dashou_11','laoban_02',13,5,'系统默认好评（结单3天未评价）','',NULL,'normal','','',NULL,'2026-08-17 16:38:17'),(23,'dashou_04','laoban_02',15,5,'系统默认好评（结单3天未评价）','',NULL,'normal','','',NULL,'2026-08-04 16:35:17'),(24,'dashou_05','laoban_02',20,5,'系统默认好评（结单3天未评价）','',NULL,'normal','','',NULL,'2026-08-10 17:04:17'),(25,'dashou_06','laoban_02',22,5,'系统默认好评（结单3天未评价）','',NULL,'normal','','',NULL,'2026-09-07 16:08:17'),(26,'dashou_08','laoban_03',31,5,'系统默认好评（结单3天未评价）','',NULL,'normal','','',NULL,'2026-08-15 17:01:17'),(27,'dashou_05','laoban_03',32,5,'系统默认好评（结单3天未评价）','',NULL,'normal','','',NULL,'2026-09-04 17:02:17'),(28,'dashou_04','laoban_03',33,5,'系统默认好评（结单3天未评价）','',NULL,'normal','','',NULL,'2026-08-27 17:59:17'),(30,'dashou_03','laoban_03',24,5,'系统默认好评（结单3天未评价）','',NULL,'normal','','',NULL,'2026-09-11 17:02:17');
/*!40000 ALTER TABLE `player_ratings` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `player_tags`
--

DROP TABLE IF EXISTS `player_tags`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `player_tags` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `tag` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `note` text COLLATE utf8mb4_unicode_ci,
  `created_at` datetime DEFAULT NULL,
  `processed_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_player_tags_id` (`id`),
  KEY `ix_player_tags_username` (`username`)
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `player_tags`
--

LOCK TABLES `player_tags` WRITE;
/*!40000 ALTER TABLE `player_tags` DISABLE KEYS */;
INSERT INTO `player_tags` VALUES (1,'dashou_07','王者百星','approved','','2026-09-10 13:55:18','2026-09-06 13:55:17'),(2,'dashou_07','国服打野','approved','','2026-09-10 13:55:18','2026-09-01 13:55:17'),(3,'dashou_07','语音带飞','approved','','2026-09-10 13:55:18','2026-09-07 13:55:17'),(4,'dashou_08','百星王者','approved','','2026-09-10 13:55:18','2026-09-04 13:55:17'),(5,'dashou_08','吃鸡指挥','approved','','2026-09-10 13:55:18','2026-08-29 13:55:17'),(6,'dashou_08','深夜可约','approved','','2026-09-10 13:55:18','2026-08-29 13:55:17'),(7,'dashou_09','峡谷千分','approved','','2026-09-10 13:55:18','2026-08-22 13:55:17'),(8,'dashou_09','中单带飞','approved','','2026-09-10 13:55:18','2026-09-01 13:55:17'),(9,'dashou_10','高端局护航','approved','','2026-09-10 13:55:18','2026-09-09 13:55:17'),(10,'dashou_10','节奏大师','approved','','2026-09-10 13:55:18','2026-09-07 13:55:17'),(11,'dashou_11','原神深渊','approved','','2026-09-10 13:55:18','2026-09-04 13:55:17'),(12,'dashou_11','巅峰2000','approved','','2026-09-10 13:55:18','2026-09-04 13:55:17'),(13,'dashou_11','全天可约','approved','','2026-09-10 13:55:18','2026-09-05 13:55:17'),(14,'dashou_12','声音好听','approved','','2026-09-10 13:55:18','2026-08-28 13:55:17'),(15,'dashou_12','欢乐陪玩','approved','','2026-09-10 13:55:18','2026-08-23 13:55:17');
/*!40000 ALTER TABLE `player_tags` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `salary_records`
--

DROP TABLE IF EXISTS `salary_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `salary_records` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_id` int NOT NULL,
  `player_username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `order_total` int NOT NULL,
  `club_commission` int NOT NULL,
  `player_income` int NOT NULL,
  `settlement_time` datetime DEFAULT NULL,
  `payout_status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `order_id` (`order_id`),
  KEY `ix_salary_records_id` (`id`),
  CONSTRAINT `salary_records_ibfk_1` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=30 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `salary_records`
--

LOCK TABLES `salary_records` WRITE;
/*!40000 ALTER TABLE `salary_records` DISABLE KEYS */;
INSERT INTO `salary_records` VALUES (1,2,'dashou_09',15400,4620,10780,'2026-08-31 18:01:17','paid'),(2,3,'dashou_09',7300,2190,5110,'2026-08-15 17:58:17','paid'),(3,4,'dashou_09',16400,4920,11480,'2026-07-28 15:36:17','paid'),(4,5,'dashou_11',12800,3840,8960,'2026-08-01 15:10:17','paid'),(5,6,'dashou_08',8700,2610,6090,'2026-08-21 17:02:17','paid'),(6,7,'dashou_08',7100,2130,4970,'2026-08-07 15:58:17','paid'),(7,8,'dashou_10',9100,2730,6370,'2026-08-01 15:37:17','paid'),(8,9,'dashou',10600,3180,7420,'2026-08-30 16:35:17','paid'),(9,10,'dashou_05',20000,6000,14000,'2026-08-21 15:08:17','paid'),(10,11,'dashou',7600,2280,5320,'2026-08-23 15:35:17','paid'),(11,13,'dashou_11',12400,3720,8680,'2026-08-14 16:38:17','paid'),(12,14,'dashou_11',11100,3330,7770,'2026-08-03 15:34:17','paid'),(13,15,'dashou_04',12500,3750,8750,'2026-08-01 16:35:17','paid'),(14,16,'dashou_03',10000,3000,7000,'2026-08-15 16:09:17','paid'),(15,17,'dashou',7700,2310,5390,'2026-09-03 17:04:17','paid'),(16,18,'dashou_06',4700,1410,3290,'2026-09-05 18:10:17','paid'),(17,19,'dashou_02',12300,3690,8610,'2026-07-28 16:33:17','paid'),(18,20,'dashou_05',18000,5400,12600,'2026-08-07 17:04:17','paid'),(19,21,'dashou_02',6100,1830,4270,'2026-09-02 16:35:17','paid'),(20,22,'dashou_06',18300,5490,12810,'2026-09-04 16:08:17','paid'),(21,24,'dashou_03',6700,2010,4690,'2026-09-08 17:02:17','paid'),(22,25,'dashou_02',14900,4470,10430,'2026-08-21 15:32:17','paid'),(23,26,'dashou_11',17700,5310,12390,'2026-08-24 16:01:17','paid'),(24,27,'dashou_08',3100,930,2170,'2026-08-24 16:37:17','paid'),(25,29,'dashou_08',16500,4950,11550,'2026-08-20 15:28:17','paid'),(26,30,'dashou_03',10400,3120,7280,'2026-08-12 18:00:17','paid'),(27,31,'dashou_08',15500,4650,10850,'2026-08-12 17:01:17','paid'),(28,32,'dashou_05',18700,5610,13090,'2026-09-01 17:02:17','paid'),(29,33,'dashou_04',12500,3750,8750,'2026-08-24 17:59:17','paid');
/*!40000 ALTER TABLE `salary_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tip_records`
--

DROP TABLE IF EXISTS `tip_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tip_records` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_id` int NOT NULL,
  `boss_username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `player_username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `amount` int NOT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `order_id` (`order_id`),
  KEY `ix_tip_records_player_username` (`player_username`),
  KEY `ix_tip_records_id` (`id`),
  CONSTRAINT `tip_records_ibfk_1` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tip_records`
--

LOCK TABLES `tip_records` WRITE;
/*!40000 ALTER TABLE `tip_records` DISABLE KEYS */;
INSERT INTO `tip_records` VALUES (1,3,'laoban','dashou_09',1095,'2026-08-15 18:16:17'),(2,5,'laoban','dashou_11',640,'2026-08-01 16:47:17'),(3,7,'laoban','dashou_08',568,'2026-08-07 17:23:17'),(4,10,'laoban','dashou_05',1600,'2026-08-21 15:58:17'),(5,13,'laoban_02','dashou_11',2480,'2026-08-14 17:30:17'),(6,14,'laoban_02','dashou_11',1110,'2026-08-03 16:25:17'),(7,16,'laoban_02','dashou_03',1000,'2026-08-15 17:12:17'),(8,20,'laoban_02','dashou_05',1800,'2026-08-07 17:26:17'),(9,24,'laoban_03','dashou_03',335,'2026-09-08 18:49:17');
/*!40000 ALTER TABLE `tip_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password_hash` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `role` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `role_name` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `nickname` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `avatar` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `pending_nickname` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `pending_avatar` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `nickname_status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `avatar_status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reject_reason` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `failed_attempts` int DEFAULT NULL,
  `lock_until` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `account_status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT 'approved',
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_users_username` (`username`),
  KEY `ix_users_id` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=24 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (1,'guanliyuan','$2b$12$UNxAgiXrTAx2iYZfAw2z3eos.MRG4NFKaz0fad/MU4VoqPofKv84S','admin','管理员','店长','avatar_admin.jpg','','','approved','approved','',0,NULL,'2026-09-10 13:47:22','approved'),(2,'kefu','$2b$12$FaOvPjMaSCsCUHd4jLmzD.2uJ3q/McyOH64dTuYIYaE0vXOGRpb8W','service','客服','客服小蜜','avatar_service.png','','','approved','approved','',0,NULL,'2026-09-10 13:47:22','approved'),(3,'laoban','$2b$12$yVU6PqDufe/Qh8dfa6R1vuqYyUekFuFHmANZDToIR4TJ.3Bo1WHc2','boss','老板','老板阿昊','avatar_boss.png','','','approved','approved','',0,NULL,'2026-09-10 13:47:22','approved'),(4,'laoban_02','$2b$12$prf3KJWc4DAmeKZ1I6DPn.K/sE4dfSMKJ086nLBik1h.CinniM6Jq','boss','老板','老板二狗','avatar_boss.png','','','approved','approved','',0,NULL,'2026-09-10 13:47:22','approved'),(5,'laoban_03','$2b$12$s1QrEVwHfCdsqcWz4NWKLeiLsEu.OTXSGvxrutvZqPPXN5p9E39RK','boss','老板','老板三少','avatar_boss.png','','','approved','approved','',0,NULL,'2026-09-10 13:47:22','approved'),(6,'dashou','$2b$12$RjEq5IijAgBsuHI3bmYBw.ZYAFqz8pFsGlljbegXwbvOWKiLl1oaO','player','打手','小达','avatar_mowanghu.jpg','','','approved','approved','',0,NULL,'2026-09-10 13:47:22','approved'),(7,'dashou_02','$2b$12$zDd/4nPs3nO5GU3wvt0DW.1Ll2DhedqNw3rn.BsG6UAtzdnduxSlW','player','打手','阿岚','avatar_211_2.jpg','','','approved','approved','',0,NULL,'2026-09-10 13:47:22','approved'),(8,'dashou_03','$2b$12$iIlux1FZdCThSON5X7AnMeT9aDZxNhBHxXNbiZSyqUUA2annSIUNe','player','打手','老猫','avatar_yule.jpg','','','approved','approved','',0,NULL,'2026-09-10 13:47:22','approved'),(9,'dashou_04','$2b$12$Ysl6m46MDKlK1W9iOzfQwe6ojBh2ik5phByWl5KMCBMEfdWzuxCx.','player','打手','北冥','avatar_985_2.jpg','','','approved','approved','',0,NULL,'2026-09-10 13:47:22','approved'),(10,'dashou_05','$2b$12$xRUWNY.KJmPvHCb4V6Vth.5wZg8lbW266AykygrfsNczL6bTIHr9.','player','打手','阿澈','avatar_dazhuan.png','','','approved','approved','',0,NULL,'2026-09-10 13:47:22','approved'),(11,'dashou_06','$2b$12$Q4tF1GKA4cjVRv33eZZbgeXyWOhqIw3lw63YX8JwsC6e6vJ9vCFuS','player','打手','星火','avatar_mingxing.jpg','','','approved','approved','',0,NULL,'2026-09-10 13:47:22','approved'),(12,'dashou_07','$2b$12$itlH5GKntKvEWDrkpMDtaOC3HhKOfvqx2dmOhrCLWFoK9bFnBz/BK','player','打手','阿泽','avatar_985_2.jpg','','','approved','approved','',0,NULL,'2026-09-10 13:55:18','approved'),(13,'dashou_08','$2b$12$0ktiziIqnMkwj6qRb5wp.e8lfi.RXDtP6.knEjCovt3ePZfKga3qO','player','打手','老六','avatar_211_2.jpg','','','approved','approved','',0,NULL,'2026-09-10 13:55:18','approved'),(14,'dashou_09','$2b$12$swz3i3pNx7p2eDAWE5g5Huyu4NlT0QTKdNfAIN7JTrQoi28LKYWrG','player','打手','小杰','avatar_dazhuan.png','','','approved','approved','',0,NULL,'2026-09-10 13:55:18','approved'),(15,'dashou_10','$2b$12$CcWMSTo5NcCX8AzwcFjYB.8Z7apvIAGWQ3rr8LWH7SStc/y2RSVDK','player','打手','夜煞','avatar_mowanghu.jpg','','','approved','approved','',0,NULL,'2026-09-10 13:55:18','approved'),(16,'dashou_11','$2b$12$6.Sn//6AYzoGQivGDwmwV.e5Htdf3BsK9Vd.q30skLGMLyZhxJ.ZK','player','打手','神谕','avatar_mingxing.jpg','','','approved','approved','',0,NULL,'2026-09-10 13:55:18','approved'),(17,'dashou_12','$2b$12$.xvNRnaSBBPvSTxHgivN4.QmYRZ9yi3B7vqYprz2fr9idP1/vt32.','player','打手','软糖','avatar_yule.jpg','','','approved','approved','',0,NULL,'2026-09-10 13:55:18','approved');
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `withdrawal_records`
--

DROP TABLE IF EXISTS `withdrawal_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `withdrawal_records` (
  `id` int NOT NULL AUTO_INCREMENT,
  `player_username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `amount` int NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `note` text COLLATE utf8mb4_unicode_ci,
  `created_at` datetime DEFAULT NULL,
  `processed_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_withdrawal_records_player_username` (`player_username`),
  KEY `ix_withdrawal_records_id` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `withdrawal_records`
--

LOCK TABLES `withdrawal_records` WRITE;
/*!40000 ALTER TABLE `withdrawal_records` DISABLE KEYS */;
INSERT INTO `withdrawal_records` VALUES (1,'dashou_05',25592,'rejected','收款信息有误，请核对后重新申请','2026-08-30 13:55:17','2026-09-08 13:55:17'),(2,'dashou_04',51043,'approved','已到账','2026-09-04 13:55:17','2026-08-28 13:55:17'),(3,'dashou_10',1216,'pending','','2026-09-09 13:55:17',NULL),(4,'dashou_09',3622,'pending','','2026-09-08 13:55:17',NULL),(5,'dashou_02',52858,'pending','','2026-09-10 13:55:17',NULL),(6,'dashou_08',4768,'pending','','2026-09-08 13:55:17',NULL);
/*!40000 ALTER TABLE `withdrawal_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping routines for database 'game_escort_club'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-09-11 18:00:23
