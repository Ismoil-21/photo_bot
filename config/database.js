const mongoose = require("mongoose");

/* =========================
   DB CONNECT
========================= */
async function connectDB() {
  try {
    await mongoose.connect("mongodb+srv://Ismoil18_db_user:yUsS5lkh2JEgBxUp@cluster0.6lisl9o.mongodb.net/photo_bot");
    console.log("MongoDB connected");
  } catch (error) {
    console.log("MongoDB error:", error);
  }
}

const mongoose = require("mongoose");

/* =========================
   USER SCHEMA
========================= */
const userSchema = new mongoose.Schema({
  telegramId: {
    type: Number,
    unique: true,
    required: true,
  },

  username: String,
  firstName: String,

  photosProcessed: {
    type: Number,
    default: 0,
  },

  createdAt: {
    type: Date,
    default: Date.now,
  },
});

const User = mongoose.model("User", userSchema);

/* =========================
   IMAGE SCHEMA
   (rasmlar alohida collectionda)
========================= */
const mongoose = require("mongoose");

const imageSchema = new mongoose.Schema({
  telegramId: {
    type: Number,
    required: true,
    index: true,
  },

  fileName: String,
  mimeType: String,

  url: {
    type: String, // 🔥 rasmning o'zi shu URL orqali
    required: true,
  },

  size: Number,

  createdAt: {
    type: Date,
    default: Date.now,
  },
});

const Image = mongoose.model("Image", imageSchema);

/* =========================
   USER FUNCTIONS
========================= */
async function addUser(userData) {
  try {
    const existingUser = await User.findOne({
      telegramId: userData.id,
    });

    if (!existingUser) {
      await User.create({
        telegramId: userData.id,
        username: userData.username,
        firstName: userData.first_name,
      });

      console.log("User added");
    }
  } catch (error) {
    console.log(error);
  }
}

/* =========================
   IMAGE FUNCTIONS
========================= */

// rasm qo‘shish
async function addImage(telegramId, url, publicId = null) {
  try {
    await Image.create({
      telegramId,
      url,
      publicId,
    });

    await User.updateOne({ telegramId }, { $inc: { photosProcessed: 1 } });
  } catch (error) {
    console.log(error);
  }
}

// user rasmlarini olish
async function getUserImages(telegramId) {
  try {
    return await Image.find({ telegramId });
  } catch (error) {
    console.log(error);
    return [];
  }
}

// user olish
async function getUser(telegramId) {
  return await User.findOne({ telegramId });
}

/* =========================
   EXPORTS
========================= */
module.exports = {
  connectDB,
  addUser,
  addImage,
  getUser,
  getUserImages,
};
